#!/bin/bash
# GCE startup-script: запускає вузол PARCS-Python у Docker на Container-Optimized OS.
#
# Замінює `gcloud compute instances create-with-container` з оригінального гайду:
# Google вимкнув container startup agent 31.07.2026, тож ця команда більше не працює.
#
# Роль вузла береться з metadata ВМ "parcs-args" (аналог PARCS_ARGS з гайду):
#   parcs-args=master                       -> master (веб-інтерфейс на :8080)
#   parcs-args=worker <ВНУТРІШНІЙ_IP_MASTER> -> worker
#
# Логи: sudo journalctl -u google-startup-scripts | tail ;  docker logs parcs

MD=http://metadata.google.internal/computeMetadata/v1/instance/attributes
PARCS_ARGS=$(curl -sf -H "Metadata-Flavor: Google" "$MD/parcs-args")
echo "PARCS_ARGS=$PARCS_ARGS"

# COS за замовчуванням відкидає всі вхідні з'єднання, крім SSH. PARCS (Pyro4)
# слухає випадкові порти, тож приймаємо TCP; ззовні доступ і далі обмежує VPC firewall.
iptables -w -A INPUT -p tcp -j ACCEPT

IMAGE=hummer12007/parcs-node
if ! docker pull "$IMAGE"; then
  # Запасний план, якщо готовий образ недоступний. Оригінальний Dockerfile
  # (debian:stretch + незафіксовані версії) вже не збирається, тому збираємо
  # на python:2.7.18 з версіями бібліотек, які ще підтримують Python 2.7.
  docker build -t parcs-node-local - <<'DOCKERFILE'
FROM python:2.7.18
RUN git clone --depth 1 https://github.com/Hummer12007/parcs-python /parcs
WORKDIR /parcs
RUN pip install --no-cache-dir Pyro4==4.82 Flask==1.1.4 py-cpuinfo==5.0.0 \
    netifaces==0.11.0 requests==2.27.1
CMD ["./run.sh"]
DOCKERFILE
  IMAGE=parcs-node-local
fi

docker rm -f parcs >/dev/null 2>&1
# --network host: контейнер бачить внутрішній IP ВМ (hostname -I) і саме його
# воркер реєструє в master. У bridge-мережі він зареєстрував би 172.17.x.x,
# до якого master не достукається.
docker run -d --name parcs --restart unless-stopped --network host \
  -e PARCS_ARGS="$PARCS_ARGS" "$IMAGE"
