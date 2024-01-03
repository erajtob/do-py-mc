import digitalocean
import sys
import time
import logging

# Setup logging
logging.basicConfig(filename='latest.log', level=logging.INFO, format='%(asctime)s %(message)s')

def read_api_token():
    with open('config.txt', 'r') as file:
        for line in file:
            if line.startswith('API='):
                return line.strip().split('=')[1]
    raise ValueError("API token not found in config file")

def create_droplet(manager):
    # Retrieve all SSH keys associated with the account
    keys = manager.get_all_sshkeys()

    droplet = digitalocean.Droplet(token=manager.token,
                                   name='ExampleDroplet',
                                   region='blr1',  # Bangalore region
                                   image='fedora-39-x64',  # Fedora 39 x64
                                   size_slug='s-1vcpu-1gb',  # 1vCPU, 1GB RAM
                                   ssh_keys=keys,  # Attaching all SSH keys
                                   backups=False)
    droplet.create()
    logging.info(f"Droplet created with ID: {droplet.id}")
    print(f"Droplet created with ID: {droplet.id}")
    return droplet

def shutdown_and_snapshot(droplet):
    droplet.shutdown(return_dict=True)
    logging.info("Droplet shutdown initiated.")
    print("Droplet shutdown initiated.")

    # Wait for droplet to power off
    actions = droplet.get_actions()
    for action in actions:
        action.load()
        if action.type == 'shutdown':
            while action.status != 'completed':
                time.sleep(10)
                action.load()
            break

    logging.info("Droplet is powered off.")
    print("Droplet is powered off.")

    # Take a snapshot
    snapshot = droplet.take_snapshot("Snapshot-{}".format(droplet.id), return_dict=True)
    snapshot_id = snapshot['action']['id']

    # Wait for snapshot to complete
    action = digitalocean.Action(token=droplet.token, id=snapshot_id)
    action.load()
    while action.status != 'completed':
        time.sleep(10)
        action.load()

    logging.info(f"Snapshot completed with ID: {snapshot_id}")
    print(f"Snapshot completed with ID: {snapshot_id}")

    # Save snapshot ID
    with open('snapshot_id.txt', 'w') as file:
        file.write(str(snapshot_id))

    # Destroy droplet
    droplet.destroy()
    logging.info("Droplet destroyed.")
    print("Droplet destroyed.")

def main():
    token = read_api_token()
    manager = digitalocean.Manager(token=token)

    if len(sys.argv) < 2:
        print("Usage: python script.py [create|destroy]")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == 'create':
        droplet = create_droplet(manager)
    elif command == 'destroy':
        droplet_id = input("Enter the Droplet ID to destroy: ")
        droplet = digitalocean.Droplet(token=token, id=droplet_id)
        shutdown_and_snapshot(droplet)
    else:
        print("Invalid command.")
        sys.exit(1)

if __name__ == "__main__":
    main()