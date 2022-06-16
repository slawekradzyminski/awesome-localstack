## Intro

Localstack for my trainings

## Running

```commandline
docker-compose up -d
```

## Verification

Backend - [http://localhost:4001/swagger-ui.html](http://localhost:4001/swagger-ui.html)

Frontend - [http://localhost:8081/login](http://localhost:8081/login)

Prometheus - [http://localhost:9090/](http://localhost:9090/)

Grafana - [http://localhost:3000/login](http://localhost:3000/login) (admin/grafana)

## Cleanup

```commandline
docker-compose down
```

## Prometheus & Graphana

[Article](https://stackabuse.com/monitoring-spring-boot-apps-with-micrometer-prometheus-and-grafana/)

## Backend

[https://github.com/slawekradzyminski/test-secure-backend](https://github.com/slawekradzyminski/test-secure-backend)

## Frontend

[https://github.com/slawekradzyminski/test-secure-frontend](https://github.com/slawekradzyminski/test-secure-frontend)

## Docker cleanup

```commandline
docker stop $(docker ps -a -q) && docker rm $(docker ps -a -q)
```