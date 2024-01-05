import digitalocean
import sys
import time
import logging
import datetime
import os

# Setup logging
logging.basicConfig(filename='latest.log', level=logging.INFO, format='%(asctime)s %(message)s')

def read_config():
    config = {'API': None, 'VOLUME': None}
    config_path = 'config.txt'

    if not os.path.exists(config_path):
        logging.error(f"Configuration file not found: {config_path}")
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    try:
        with open(config_path, 'r') as file:
            for line in file:
                if line.startswith('API='):
                    config['API'] = line.strip().split('=')[1]
                elif line.startswith('VOLUME='):
                    config['VOLUME'] = line.strip().split('=')[1]
    except IOError as e:
        logging.error(f"Error reading configuration file: {e}")
        raise IOError(f"Error reading configuration file: {e}")

    if not config['API']:
        raise ValueError("API token not found in config file")

    return config

def wait_for_action_completion(droplet, action_type):
    action_complete = False
    while not action_complete:
        actions = droplet.get_actions()
        for action in actions:
            action.load()
            if action.type == action_type and action.status == 'completed':
                action_complete = True
                break
        time.sleep(3)
    logging.info(f"Action {action_type} completed for droplet {droplet.id}.")
    print(f"Action {action_type} completed for droplet {droplet.id}.")

def wait_for_volume_detachment(manager, droplet_id, volume_id):
    while True:
        droplet = manager.get_droplet(droplet_id)
        droplet.load()
        if volume_id not in droplet.volume_ids:
            logging.info(f"Volume {volume_id} successfully detached from droplet {droplet_id}.")
            print(f"Volume {volume_id} successfully detached from droplet {droplet_id}.")
            break
        time.sleep(3)

def cleanup_droplet(manager, droplet_id):
    try:
        droplet = manager.get_droplet(droplet_id)
        droplet.destroy()
        logging.info(f"Cleaned up droplet with ID: {droplet_id}")
    except Exception as e:
        logging.error(f"Failed to clean up droplet: {e}")

def cleanup_volume(manager, volume_id):
    try:
        volume = manager.get_volume(volume_id)
        volume.destroy()
        logging.info(f"Cleaned up volume with ID: {volume_id}")
    except Exception as e:
        logging.error(f"Failed to clean up volume: {e}")

def create_volume(manager, region, size_gigabytes, name):
    volume = digitalocean.Volume(token=manager.token,
                                 region=region,
                                 size_gigabytes=size_gigabytes,
                                 name=name)
    volume.create()
    logging.info(f"Volume created with ID: {volume.id}")
    print(f"Volume created with ID: {volume.id}")
    return volume

def create_droplet(manager, volume):
    droplet = None
    creation_successful = False

    try:
        keys = manager.get_all_sshkeys()
        droplet = digitalocean.Droplet(token=manager.token,
                                    name='ExampleDroplet',
                                    region='blr1',
                                    image='fedora-39-x64',
                                    size_slug='s-1vcpu-1gb',
                                    ssh_keys=keys,
                                    volumes=[volume.id],  # Attach volume during creation
                                    backups=False)
        droplet.create()
        logging.info(f"Droplet created with ID: {droplet.id}, with volume {volume.id} attached")
        print(f"Droplet created with ID: {droplet.id}, with volume {volume.id} attached")

        wait_for_action_completion(droplet, 'create')

        creation_successful = True
        return droplet

    except Exception as e:
        logging.error(f"Error during droplet creation: {e}")
        raise
    finally:
        if droplet and not creation_successful:
            cleanup_droplet(manager, droplet.id)

def restore_droplet_from_snapshot(manager, volume_id):
    # Read snapshot ID from file
    with open('snapshot_id.txt', 'r') as file:
        snapshot_id = file.read().strip()

    # Check if the snapshot ID exists
    try:
        snapshot = manager.get_image(snapshot_id)
        logging.info(f"Snapshot found: {snapshot_id}")
    except digitalocean.NotFoundError:
        logging.error(f"Snapshot ID not found: {snapshot_id}")
        print(f"Snapshot ID not found: {snapshot_id}")
        return

    keys = manager.get_all_sshkeys()

    # Create a droplet from the snapshot with the volume attached
    droplet = digitalocean.Droplet(token=manager.token,
                                   name='RestoredDroplet',
                                   region='blr1',
                                   size_slug='s-1vcpu-1gb',
                                   image=snapshot_id,
                                   ssh_keys=keys,
                                   volumes=[volume_id],  # Attach volume during creation
                                   backups=False)
    droplet.create()
    logging.info(f"Restoration of droplet {droplet.id} initiated from snapshot {snapshot_id}.")
    print(f"Restoration of droplet {droplet.id} initiated from snapshot {snapshot_id}.")

    # Wait for droplet creation to complete
    wait_for_action_completion(droplet, 'create')

def shutdown_and_snapshot(manager, droplet_id, skip_snapshot=False):
    droplet = manager.get_droplet(droplet_id)

    # Initiate droplet shutdown
    droplet.shutdown()
    logging.info("Droplet shutdown initiated.")
    print("Droplet shutdown initiated.")

    # Wait for droplet to be powered off
    wait_for_action_completion(droplet, 'shutdown')

    # Detach volumes before snapshotting/destroying
    droplet.load()
    if droplet.volume_ids:
        for volume_id in droplet.volume_ids:
            volume = manager.get_volume(volume_id)
            volume.detach(droplet.id, droplet.region['slug'])
            logging.info(f"Initiating detachment of volume {volume.id} from droplet {droplet.id}")
            print(f"Initiating detachment of volume {volume.id} from droplet {droplet.id}")

        # Wait for each volume to be detached
        for volume_id in droplet.volume_ids:
            wait_for_volume_detachment(manager, droplet.id, volume_id)

    if skip_snapshot:
        logging.info("Skipping snapshot creation as per request.")
        print("Skipping snapshot creation as per request.")
    else:
        # Proceed with snapshot logic
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        snapshot_name = f"Snapshot-{droplet.id}-{timestamp}"

        droplet.take_snapshot(snapshot_name, return_dict=True)
        logging.info(f"Snapshot initiation for droplet {droplet.id} started.")
        print(f"Snapshot initiation for droplet {droplet.id} started.")

        wait_for_action_completion(droplet, 'snapshot')

        # Fetch the snapshot by name
        snapshots = manager.get_all_snapshots()
        my_snapshot = next((snap for snap in snapshots if snap.name == snapshot_name), None)

        if my_snapshot:
            snapshot_id = my_snapshot.id
            logging.info(f"Snapshot completed with ID: {snapshot_id}")
            print(f"Snapshot completed with ID: {snapshot_id}")

            # Save snapshot ID
            with open('snapshot_id.txt', 'w') as file:
                file.write(str(snapshot_id))
        else:
            logging.error(f"No snapshot with name {snapshot_name} found.")
            print(f"No snapshot with name {snapshot_name} found.")

    # Destroy droplet
    droplet.destroy()
    logging.info("Droplet destroyed.")
    print("Droplet destroyed.")

def main():
    config = read_config()
    manager = digitalocean.Manager(token=config['API'])

    if len(sys.argv) < 2:
        print("Usage: python script.py [create|destroy|restore]")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == 'create':
        volume = create_volume(manager, 'blr1', 10, 'examplevolume2')
        droplet = create_droplet(manager, volume)
    elif command == 'destroy':
        droplet_id = input("Enter the Droplet ID to destroy: ")
        skip_snapshot = '-s' in sys.argv
        shutdown_and_snapshot(manager, droplet_id, skip_snapshot)
    elif command == 'restore':
        restore_droplet_from_snapshot(manager, config['VOLUME'])
    else:
        print("Invalid command.")
        sys.exit(1)

if __name__ == "__main__":
    main()