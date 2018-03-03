from yaml import load, Loader

job_config = {}
server_config = None

def load_server_config(file_name):
    with open(file_name) as f:
        global server_config
        server_config = load(f, Loader=Loader)

def get_server_config():
    return server_config
