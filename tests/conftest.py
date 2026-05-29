import os

# Set socket timeout to 0 so tests don't hang and fail/pass immediately
os.environ["SOCKET_WAIT_TIMEOUT"] = "0"

# Skip global chrome driver initialization during test startup
os.environ["SKIP_GLOBAL_DRIVER_INIT"] = "true"
