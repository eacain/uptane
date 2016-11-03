"""
__init__.py for the Uptane demo package
"""

import uptane
import os
import tuf.formats
import tuf.repository_tool as rt

DEMO_DIR = os.path.join(uptane.WORKING_DIR, 'demo')
DEMO_KEYS_DIR = os.path.join(DEMO_DIR, 'keys')
DEMO_PINNING_FNAME = os.path.join(DEMO_DIR, 'pinned.json')

MAIN_REPO_HOST = 'localhost' #'http://192.168.1.124'
MAIN_REPO_PORT = 30301
MAIN_REPO_NAME = 'repomain'
MAIN_REPO_DIR = os.path.join(uptane.WORKING_DIR, MAIN_REPO_NAME)
MAIN_REPO_TARGETS_DIR = os.path.join(MAIN_REPO_DIR, 'targets')
MAIN_REPO_ROOT_FNAME = os.path.join(MAIN_REPO_DIR, 'metadata', 'root.json')

DIRECTOR_REPO_HOST = 'localhost' #'http://192.168.1.124'
DIRECTOR_REPO_PORT = 30401
DIRECTOR_REPO_NAME = 'repodirector'
DIRECTOR_REPO_DIR = os.path.join(uptane.WORKING_DIR, DIRECTOR_REPO_NAME)
DIRECTOR_REPO_TARGETS_DIR = os.path.join(DIRECTOR_REPO_DIR, 'targets')
DIRECTOR_REPO_ROOT_FNAME = os.path.join(DIRECTOR_REPO_DIR, 'metadata', 'root.json')

DIRECTOR_SERVER_HOST = '0.0.0.0' #'localhost'
DIRECTOR_SERVER_PORT = 30501

TIMESERVER_HOST = '0.0.0.0' #'localhost'
TIMESERVER_PORT = 30601

PRIMARY_SERVER_HOST = 'localhost'
PRIMARY_SERVER_PORT = 30701

SECONDARY_SERVER_HOST = 'localhost'
SECONDARY_SERVER_PORT = 30801



def generate_key(keyname):
  """
  Generate a key pair according to the demo's current default key config.

    Passphrase: 'pw'
    Key type: ed25519
    Key location: DEMO_KEYS_DIR
  """
  rt.generate_and_write_ed25519_keypair(
      os.path.join(DEMO_KEYS_DIR, keyname), password='pw')



def import_public_key(keyname):
  """
  Import a public key according to the demo's current default key config.
  The keyname does not include '.pub'; it matches that used for the other
  functions here.

    Key type: ed25519
    Key location: DEMO_KEYS_DIR
  """
  return rt.import_ed25519_publickey_from_file(
      os.path.join(DEMO_KEYS_DIR, keyname + '.pub'))



def import_private_key(keyname):
  """
  Import a private key according to the demo's current default key config.

    Passphrase: 'pw'
    Key type: ed25519
    Key location: DEMO_KEYS_DIR
  """
  return rt.import_ed25519_privatekey_from_file(
      os.path.join(DEMO_KEYS_DIR, keyname), password='pw')
