#/bin/bash
docker build -t aggregator .
docker run -it -p 8002:8002 aggregator bash

