NETSKOPE_CERT = /Library/Application Support/Netskope/STAgent/data/nscacert.pem

install-playwright:
	NODE_EXTRA_CA_CERTS="$(NETSKOPE_CERT)" python3 -m playwright install chromium

prereq:
	nerdctl compose -f deploy/docker-compose.yaml up -d

kill:
	pkill -f "uvicorn main:app" && echo "killed"

restart:
	pkill -f "uvicorn main:app" || true
	sleep 2
	cd /Users/amar/context_processor && uvicorn main:app --reload --host 0.0.0.0 --port 8000 >> /tmp/context_processor.log 2>&1 &
	echo "restarted"