# README for Docker Project

## Overview
This Docker image is used to run experiments on parallel processing of dtmri models in dipy. It returns its data as csv files that can either be automaticaly sent to and s3 bucket, or will be saved locally

## Pull from DockerHub
To pull from DockerHub run:
docker pull asaagilmore/dipy-parallel-tests

## Building the Docker Image
To build the Docker image, navigate to the directory containing the Dockerfile and run:
docker build . -t image_name


## Running the Container
To run the container with command-line arguments, use the following syntax. Replace `your-image-name` with the name you assigned during the build process, and replace the arguments as necessary:

docker run your-image-name --models csdm --hcp_access_key_id YOUR_KEY --hcp_secret_access_key YOUR_SECRET --s3_access_key_id YOUR_KEY --s3_secret_access_key YOUR_SECRET --min_scale 1 --max_scale 5 --min_chunks 1 --max_chunks 5 --num_runs 3 --filename output.csv --s3bucket your-bucket-name

Note: docker containers will by default make dev/shm a fairly small directory, which is used by ray for swap. If dealing with data that may spill out of memory run with docker run --shm-size=100gb, or however much space you think you might need

if testing number of cpus, you can limit the containers access to cpus by adding the argument --cpuset-cpus 0-x where x is the number of cpus you want minus 1
unfortunatly the detected number of cpus inside the container will still be the number of hardware cores that exist, so manually overrride this via the --num_cpus arg

## Argument Details
- `--models`: Models to run (e.g., `csdm`, `fwdtim`).
- `--hcp_access_key_id`, `--hcp_secret_access_key`: The AWS credentials for accessing HCP data, Keys can be obtained [here](https://db.humanconnectome.org/)
- `--s3_access_key_id`, `--s3_secret_access_key`: AWS credentials that have write permission for the s3 bucket.
- `--min_scale`, `--max_scale`: number of scales to downsample by, default is 1-1, so no downsampling.
- `--min_chunks`, `--max_chunks`: Range of chunks to compute, # of chunks is by orders of 2, ie running with min_chunks: 2 max_chunks: 4 will run chunk sizes 2^2, 2^3, and 2^4
- `--num_runs`: Number of times to run each unique set of parameters
- `--skip_serial`: the script will by default run a serial baseline for each set of unique parameters, set this to True if you want to skip that step, otherwise DO NOT provide this argument at all
- `--filename`: Name of the output file, must have .csv extension
- `--s3bucket`: S3 bucket for storing results.
- `--num_cpus`: This overrides the number of cpus detected by python and sets the csv value manually. This is neccecary as limiting cpus via docker doesn't change the number of detected cpus inside the container.