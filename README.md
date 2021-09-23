## Intro

Localstack for my trainings

## Running

```commandline
docker-compose up -d
```

## Verification

Backend - [http://localhost:4000/swagger-ui.html](http://localhost:4000/swagger-ui.html)

Frontend - [http://localhost:8080/login](http://localhost:8080/login)

Prometheus - [http://localhost:9090/](http://localhost:9090/)

Grafana - [http://localhost:3000/login](http://localhost:3000/login)

## Cleanup

```commandline
docker-compose down
```

## Prometheus & Graphana

[Article](https://stackabuse.com/monitoring-spring-boot-apps-with-micrometer-prometheus-and-grafana/)

[JVM Dashboard id](https://grafana.com/grafana/dashboards/4701)

## Backend

[https://github.com/slawekradzyminski/test-secure-backend](https://github.com/slawekradzyminski/test-secure-backend)

## Frontend

[https://github.com/slawekradzyminski/test-secure-frontend](https://github.com/slawekradzyminski/test-secure-frontend)

## Docker cleanup

```commandline
docker stop $(docker ps -a -q) && docker rm $(docker ps -a -q)
```