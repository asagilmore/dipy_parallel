import dipy.reconst.csdeconv as csd
import dipy.reconst.fwdti as fwdti
import time
import multiprocessing
import psutil
import csv
import os
import numpy as np
import threading
import argparse
from getData import getScaledData
import boto3
import configparser
import uuid

cpu_count = multiprocessing.cpu_count()
memory_size = psutil.virtual_memory().total


def upload_to_s3(file_name, bucket, object_name=None, region_name='us-west-2',
                 aws_access_key_id=None, aws_secret_access_key=None):
    # If S3 object_name was not specified, use file_name
    if object_name is None:
        object_name = file_name

    # Upload the file
    s3_client = boto3.client('s3', region_name='us-west-2',
                             aws_access_key_id=aws_access_key_id,
                             aws_secret_access_key=aws_secret_access_key)
    response = s3_client.upload_file(file_name, bucket, object_name)
    return True


class MemoryMonitor:
    def __init__(self, interval):
        self.interval = interval
        self.memory_usage = []
        self.stop_monitor = False

    def monitor_memory(self):
        while not self.stop_monitor:
            mem_info = psutil.virtual_memory()
            used_memory_GB = mem_info.used / (1024 ** 3)
            self.memory_usage.append(used_memory_GB)
            time.sleep(self.interval)

    def get_memory_usage(self):
        return self.memory_usage, sum(self.memory_usage) / len(self.memory_usage)


runTimeData = []


# run csdm with the given engine and vox_per_chunk
# appends the given time, engine, and vox_per_chunk to the data dataframe
# returns the time it took to run
def run_fit(model, engine, data, brain_mask_data, num_chunks, save=True):

    global runTimeData, cpu_count, memory_size

    monitor = MemoryMonitor(1)

    ## calc approx vox_per_chunk from num_chunks
    non_zero_count = np.count_nonzero(brain_mask_data)
    chunk_size = non_zero_count // num_chunks
    vox_per_chunk = int(chunk_size)

    print("running with, engine: ", engine, " vox_per_chunk: ", vox_per_chunk,
          " num_chunks: ", num_chunks)

    # start tracking memory useage
    monitor_thread = threading.Thread(target=monitor.monitor_memory)
    monitor_thread.start()

    print(f'engine {engine}')
    start = time.time()
    fit = model.fit(data, mask=brain_mask_data, engine=engine,
                    vox_per_chunk=vox_per_chunk)
    end = time.time()

    #Stop tracking memeory
    monitor.stop_monitor = True
    monitor_thread.join()

    # grab memory stats
    memory_usage, average_memory_usage = monitor.get_memory_usage()

    runTime = end-start

    model_name = model.__class__.__name__

    if (save):
        runTimeData.append({'engine': engine, 'vox_per_chunk': vox_per_chunk,
                            'num_chunks': num_chunks, 'time': runTime,
                            'cpu_count': cpu_count,
                            'memory_size': memory_size,
                            'num_vox': non_zero_count,
                            'avg_mem': average_memory_usage,
                            'mem_useage': memory_usage, 'model': model_name,
                            'data_shape': data.shape})
    else:
        print("save turned off, runTime not saved")

    print("time: ", runTime)

    return runTime


def add_aws_profile(profile_name, aws_access_key_id, aws_secret_access_key):
    credentials_file = os.path.expanduser('~/.aws/credentials')


    # Check if the file exists
    if not os.path.isfile(credentials_file):
        os.makedirs(os.path.dirname(credentials_file), exist_ok=True)
        open(credentials_file, 'a').close()

    # Create a ConfigParser object
    config = configparser.RawConfigParser()

    # Read the existing AWS credentials file
    config.read(credentials_file)

    # Add the new profile
    if not config.has_section(profile_name):
        config.add_section(profile_name)
    config.set(profile_name, 'aws_access_key_id', aws_access_key_id)
    config.set(profile_name, 'aws_secret_access_key', aws_secret_access_key)

    # Write the changes back to the file
    with open(credentials_file, 'w') as f:
        config.write(f)

    print(f"Profile '{profile_name}' added to {credentials_file}")


def save_data(filename):
    global runTimeData

    # specify the names for CSV column headers
    fieldnames = runTimeData[0].keys() if runTimeData else Error("No data to save")

    # writing to csv file
    with open(filename, 'a', newline='') as csvfile:
        # creating a csv writer object
        csvwriter = csv.DictWriter(csvfile, fieldnames=fieldnames)
        # writing headers (field names) if the file doesn't exist or it is empty
        if not os.path.isfile(filename) or os.path.getsize(filename) == 0:
            csvwriter.writeheader()

        # writing the data rows
        csvwriter.writerows(runTimeData)

    runTimeData.clear()


if __name__ == "__main__":

    # parse arugments from command line
    parser = argparse.ArgumentParser()

    parser.add_argument('--min_scale', type=int, default=1)
    parser.add_argument('--max_scale', type=int, default=1)
    parser.add_argument('--num_runs', type=int, default=5)
    parser.add_argument('--min_chunks', type=int, default=0)
    parser.add_argument('--max_chunks', type=int, default=10)
    parser.add_argument('--models', type=str, default='csdm', nargs='+',
                        choices=['csdm', 'fwdtim'])
    parser.add_argument('--filename', type=str, default='data.csv')
    parser.add_argument('--skip_serial', type=bool, default=False)
    parser.add_argument('--s3bucket', type=str, default=None)
    parser.add_argument('--s3_access_key_id', type=str, default=None)
    parser.add_argument('--s3_secret_access_key', type=str, default=None)
    parser.add_argument('--hcp_access_key_id', type=str, required=True)
    parser.add_argument('--hcp_secret_access_key', type=str, required=True)
    parser.add_argument('--num_cpus', type=int, default=None)

    args = parser.parse_args()

    if args.num_cpus:
        cpu_count = args.num_cpus

    uuid = uuid.uuid4().hex
    unique_object_name = f"data_{uuid}.csv"

    add_aws_profile('hcp', args.hcp_access_key_id,
                    args.hcp_secret_access_key)

    print('running with args:', args)

    for i in range(args.min_scale, args.max_scale + 1):

        gtab, response, brain_mask_data, data = getScaledData(i)

        models = []

        if 'csdm' in args.models:
            csdm = csd.ConstrainedSphericalDeconvModel(gtab, response=response)
            models.append(csdm)
        if 'fwdtim' in args.models:
            fwdtim = fwdti.FreeWaterTensorModel(gtab)
            models.append(fwdtim)

        if len(models) == 0:
            raise ValueError("No valid models specified")

        for model in models:

            if not args.skip_serial:
                for i in range(args.num_runs):
                    print(f'running {model.__class__.__name__} with serial engine, and shape {data.shape}')
                    run_fit(model, "serial", data, brain_mask_data, 1)
                    save_data(args.filename)
                upload_to_s3(args.filename, args.s3bucket,
                             object_name=unique_object_name,
                             aws_access_key_id=args.s3_access_key_id,
                             aws_secret_access_key=args.s3_secret_access_key)
            for x in range(args.min_chunks, args.max_chunks + 1):
                num_chunks = 2**x
                print(np.prod(data.shape[:3]))
                print(num_chunks)
                if (np.prod(data.shape[:3]) > num_chunks):
                    for i in range(args.num_runs):
                        print(f'running {model.__class__.__name__} with ray engine, num_chunks {num_chunks} and shape {data.shape}')
                        run_fit(model, 'ray', data, brain_mask_data,
                                num_chunks)
                        save_data(args.filename)
                    upload_to_s3(args.filename, args.s3bucket,
                                 object_name=unique_object_name,
                                 aws_access_key_id=args.s3_access_key_id,
                                 aws_secret_access_key=args.s3_secret_access_key)
