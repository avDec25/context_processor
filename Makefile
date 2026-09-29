NETSKOPE_CERT = /Library/Application Support/Netskope/STAgent/data/nscacert.pem

install-playwright:
	NODE_EXTRA_CA_CERTS="$(NETSKOPE_CERT)" python3 -m playwright install chromium

prereq:
	@RUNNING="$$(docker inspect --format '{{.State.Running}}' pr_postgres_container 2>/dev/null)"; \
	if [ "$$RUNNING" = "true" ]; then \
		echo "Postgres container is already running"; \
	elif docker inspect pr_postgres_container >/dev/null 2>&1; then \
		echo "Removing stale Postgres container before recreating it"; \
		docker rm -f pr_postgres_container >/dev/null; \
		docker compose -f deploy/docker-compose.yaml up -d; \
	elif [ -n "$$(docker ps -q --filter 'publish=5432')" ]; then \
		echo "A Postgres container is already serving port 5432"; \
	else \
		docker compose -f deploy/docker-compose.yaml up -d; \
	fi

kill:
	pkill -f "uvicorn main:app" && echo "killed"

restart:
	pkill -f "uvicorn main:app" || true
	sleep 2
	cd /Users/ts-amar.vashishth/context_processor && uvicorn main:app --reload --host 0.0.0.0 --port 8000 >> /tmp/context_processor.log 2>&1 &
	echo "restarted"
