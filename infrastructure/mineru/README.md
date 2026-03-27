See details https://opendatalab.github.io/MinerU/quick_start/docker_deployment/

# 1. Download compose.yaml (if you don't have it yet)  
wget https://gcore.jsdelivr.net/gh/opendatalab/MinerU@master/docker/compose.yaml  
  
# 2. Download and build Docker image 
wget https://gcore.jsdelivr.net/gh/opendatalab/MinerU@master/docker/global/Dockerfile  
docker build -t mineru:latest -f Dockerfile .  

or

wget https://gcore.jsdelivr.net/gh/opendatalab/MinerU@master/docker/china/Dockerfile
docker build -t mineru:latest -f Dockerfile .
  
# 3. Start the API service
docker compose -f compose.yaml --profile api up -d