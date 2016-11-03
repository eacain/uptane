"""
demo_secondary.py

Demonstration code handling a full verification secondary client.


Use:

import demo.demo_secondary as ds
ds.clean_slate() # Director and Primary should be listening first
ds.listen()
ds.generate_signed_ecu_manifest()   # saved as ds.most_recent_signed_manifest
ds.submit_ecu_manifest_to_primary() # optionally takes different signed manifest


(Behind the scenes, that results in a few interactions, ultimately leading to:
      primary_ecu.register_ecu_manifest(
        ds.secondary_ecu.vin,
        ds.secondary_ecu.ecu_serial,
        nonce,
        manifest)



"""

import demo
import uptane
import uptane.common # for canonical key construction and signing
import uptane.clients.secondary as secondary
from uptane import GREEN, RED, YELLOW, ENDCOLORS
import tuf.keys
import tuf.repository_tool as rt
import tuf.client.updater

import os # For paths and makedirs
import shutil # For copyfile
import threading # for the demo listener
import time
import xmlrpc.client
import xmlrpc.server
import copy # for copying manifests before corrupting them during attacks

# Globals
_client_directory_name = 'temp_secondary' # name for this secondary's directory
_vin = '111'
_ecu_serial = '22222'
firmware_filename = 'secondary_firmware.txt'
current_firmware_fileinfo = {}
secondary_ecu = None
ecu_key = None
nonce = None

listener_thread = None

most_recent_signed_ecu_manifest = None


def clean_slate(
    use_new_keys=False,
    client_directory_name=_client_directory_name,
    vin=_vin,
    ecu_serial=_ecu_serial):
  """
  """

  global secondary_ecu
  global _client_directory_name
  global _vin
  global _ecu_serial
  global nonce
  global listener_thread

  _client_directory_name = client_directory_name
  _vin = vin
  _ecu_serial = ecu_serial


  # Load the public timeserver key.
  key_timeserver_pub = demo.import_public_key('timeserver')

  # Set starting firmware fileinfo (that this ECU had coming from the factory)
  factory_firmware_fileinfo = {
      'filepath': '/secondary_firmware.txt',
      'fileinfo': {
          'hashes': {
              'sha512': '706c283972c5ae69864b199e1cdd9b4b8babc14f5a454d0fd4d3b35396a04ca0b40af731671b74020a738b5108a78deb032332c36d6ae9f31fae2f8a70f7e1ce',
              'sha256': '6b9f987226610bfed08b824c93bf8b2f59521fce9a2adef80c495f363c1c9c44'},
          'length': 37}}

  # Prepare this ECU's key.
  load_or_generate_key(use_new_keys)

  # Generate a trusted initial time for the Secondary.
  clock = tuf.formats.unix_timestamp_to_datetime(int(time.time()))
  clock = clock.isoformat() + 'Z'
  tuf.formats.ISO8601_DATETIME_SCHEMA.check_match(clock)

  # Initialize a full verification Secondary ECU, making a client directory and
  # copying the root file from the repositories.
  # This also generates a nonce to use in the next time query, sets the initial
  # firmware fileinfo, etc.
  secondary_ecu = secondary.Secondary(
      full_client_dir=os.path.join(uptane.WORKING_DIR, _client_directory_name),
      pinning_filename=demo.DEMO_PINNING_FNAME,
      vin=_vin,
      ecu_serial=_ecu_serial,
      fname_root_from_mainrepo=demo.MAIN_REPO_ROOT_FNAME,
      fname_root_from_directorrepo=demo.DIRECTOR_REPO_ROOT_FNAME,
      ecu_key=ecu_key,
      time=clock,
      firmware_fileinfo=factory_firmware_fileinfo,
      timeserver_public_key=key_timeserver_pub)

  # secondary_ecu.update_time_from_timeserver(nonce)


  register_self_with_primary()
  register_self_with_director()


  print('\n' + GREEN + ' Now simulating a Secondary that rolled off the '
      'assembly line\n and has never seen an update.' + ENDCOLORS)



# Restrict director requests to a particular path.
# Must specify RPC2 here for the XML-RPC interface to work.
class RequestHandler(xmlrpc.server.SimpleXMLRPCRequestHandler):
  rpc_paths = ('/RPC2',)



def listen():
  """
  Listens on SECONDARY_SERVER_PORT for xml-rpc calls to functions
  """

  global listener_thread

  # Create server
  server = xmlrpc.server.SimpleXMLRPCServer(
      (demo.SECONDARY_SERVER_HOST, demo.SECONDARY_SERVER_PORT),
      requestHandler=RequestHandler, allow_none=True)
  #server.register_introspection_functions()

  # Register function that can be called via XML-RPC, allowing a Primary to
  # send metadata and images to the Secondary.
  server.register_function(
      secondary_ecu.receive_msg_from_primary, 'receive_msg_from_primary')

  print(' Secondary will now listen on port ' + str(demo.SECONDARY_SERVER_PORT))

  if listener_thread is not None:
    print('Sorry - there is already a Secondary thread listening.')
    return
  else:
    print(' Starting Secondary Listener Thread: will now listen on port ' +
        str(demo.SECONDARY_SERVER_PORT))
    listener_thread = threading.Thread(target=server.serve_forever)
    listener_thread.setDaemon(True)
    listener_thread.start()





def submit_ecu_manifest_to_primary(signed_ecu_manifest=None):

  global most_recent_signed_ecu_manifest
  if signed_ecu_manifest is None:
    signed_ecu_manifest = most_recent_signed_ecu_manifest


  uptane.formats.SIGNABLE_ECU_VERSION_MANIFEST_SCHEMA.check_match(
      signed_ecu_manifest)
  # TODO: <~> Be sure to update the previous line to indicate an ASN.1
  # version of the ecu_manifest after encoders have been implemented.


  server = xmlrpc.client.ServerProxy(
      'http://' + str(demo.PRIMARY_SERVER_HOST) + ':' +
      str(demo.PRIMARY_SERVER_PORT))
  #if not server.system.listMethods():
  #  raise Exception('Unable to connect to server.')

  server.submit_ecu_manifest(
      secondary_ecu.vin,
      secondary_ecu.ecu_serial,
      secondary_ecu.nonce_next,
      signed_ecu_manifest)

  secondary_ecu.rotate_nonces()





def load_or_generate_key(use_new_keys=False):
  """Load or generate an ECU's private key."""

  global ecu_key

  if use_new_keys:
    demo.generate_key('secondary')

  # Load in from the generated files.
  key_pub = demo.import_public_key('secondary')
  key_pri = demo.import_private_key('secondary')

  ecu_key = uptane.common.canonical_key_from_pub_and_pri(key_pub, key_pri)




def update_cycle():
  """
  """

  global secondary_ecu
  global current_firmware_fileinfo

  # Starting with just the root.json files for the director and mainrepo, and
  # pinned.json, the client will now use TUF to connect to each repository and
  # download/update top-level metadata. This call updates metadata from both
  # repositories.
  # upd.refresh()
  print(GREEN + '\n')
  print(' Now updating top-level metadata from the Director and OEM Repositories'
      '\n    (timestamp, snapshot, root, targets)')
  print('\n' + ENDCOLORS)
  secondary_ecu.refresh_toplevel_metadata_from_repositories()


  # Get the list of targets the director expects us to download and update to.
  # Note that at this line, this target info is not yet validated with the
  # supplier repo: that is done a few lines down.
  directed_targets = secondary_ecu.get_target_list_from_director()

  print()
  print(YELLOW + ' A correctly signed statement from the Director indicates that')

  if not directed_targets:
    print(' we have no updates to install.\n' + ENDCOLORS)
    return

  else:
    print(' that we should install these files:\n')
    for targ in directed_targets:
      print('    ' + targ['filepath'])
    print(ENDCOLORS)

  # This call determines what the right fileinfo (hash, length, etc) for
  # target file file2.txt is. This begins by matching paths/patterns in
  # pinned.json to determine which repository to connect to. Since pinned.json
  # in this case assigns all targets to a multi-repository delegation requiring
  # consensus between the two repos "director" and "mainrepo", this call will
  # retrieve metadata from both repositories and compare it to each other, and
  # only return fileinfo if it can be retrieved from both repositories and is
  # identical (the metadata in the "custom" fileinfo field need not match, and
  # should not, since the Director will include ECU IDs in this field, and the
  # mainrepo cannot.
  # In this particular case, fileinfo will match and be stored, since both
  # repositories list file2.txt as a target, and they both have matching metadata
  # for it.
  print(' Retrieving validated image file metadata from Director and OEM '
      'Repositories.')
  verified_targets = []
  for targetinfo in directed_targets:
    target_filepath = targetinfo['filepath']
    try:
      verified_targets.append(
        secondary_ecu.get_validated_target_info(target_filepath))
    except tuf.UnknownTargetError:
      print(RED + 'Director has instructed us to download a target (' +
          target_filepath + ') that is not validated by the combination of '
          'Director + Supplier repositories. Such an unvalidated file MUST NOT'
          ' and WILL NOT be downloaded, so IT IS BEING SKIPPED. It may be that'
          ' files have changed in the last few moments on the repositories. '
          'Try again, but if this happens often, you may be connecting to an '
          'untrustworthy Director, or the Director and Supplier may be out of '
          'sync.' + ENDCOLORS)


  verified_target_filepaths = [targ['filepath'] for targ in verified_targets]

  print(GREEN + '\n')
  print('Metadata for the following Targets has been validated by both '
      'the Director and the OEM repository.\nThey will now be downloaded:')
  for vtf in verified_target_filepaths:
    print('    ' + vtf)
  print(ENDCOLORS)

  # # Insist that file2.txt is one of the verified targets.
  # assert True in [targ['filepath'] == '/file2.txt' for targ in \
  #     verified_targets], 'I do not see /file2.txt in the verified targets.' + \
  #     ' Test has changed or something is wrong. The targets are: ' + \
  #     repr(verified_targets)

  # If you execute the following, commented-out command, you'll get a not found
  # error, because while the mainrepo specifies file1.txt, the Director does not.
  # Anything the Director doesn't also list can't be validated.
  # file1_trustworthy_info = secondary.updater.target('file1.txt')

  # # Delete file2.txt if it already exists. We're about to download it.
  # if os.path.exists(os.path.join(client_directory_name, 'file2.txt')):
  #   os.remove(os.path.join(client_directory_name, 'file2.txt'))


  # For each target for which we have verified metadata:
  for target in verified_targets:

    # Make sure the resulting filename is actually in the client directory.
    # (In other words, enforce a jail.)
    full_targets_directory = os.path.abspath(os.path.join(
        client_directory_name, 'targets'))
    filepath = target['filepath']
    if filepath[0] == '/':
      filepath = filepath[1:]
    full_fname = os.path.join(full_targets_directory, filepath)
    enforce_jail(filepath, full_targets_directory)

    # Delete existing targets.
    if os.path.exists(full_fname):
      os.remove(full_fname)

    # Download each target.
    # Now that we have fileinfo for all targets listed by both the Director and
    # the Supplier (mainrepo) -- which should include file2.txt in this test --
    # we can download the target files and only keep each if it matches the
    # verified fileinfo. This call will try every mirror on every repository
    # within the appropriate delegation in pinned.json until one of them works.
    # In this case, both the Director and OEM Repo are hosting the
    # file, just for my convenience in setup. If you remove the file from the
    # Director before calling this, it will still work (assuming OEM still
    # has it). (The second argument here is just where to put the files.)
    # This should include file2.txt.
    try:
      secondary_ecu.updater.download_target(target, full_targets_directory)

    except tuf.NoWorkingMirrorError as e:
      print('')
      print(YELLOW + 'In downloading target ' + repr(filepath) + ', am unable '
          'to find a mirror providing a trustworthy file.\nChecking the mirrors'
          ' resulted in these errors:')
      for mirror in e.mirror_errors:
        print('    ' + type(e.mirror_errors[mirror]).__name__ + ' from ' + mirror)
      print(ENDCOLORS)

      # If this was our firmware, notify that we're not installing.
      if filepath.startswith('/') and filepath[1:] == firmware_filename or \
        not filepath.startswith('/') and filepath == firmware_filename:

        print()
        print(YELLOW + ' While the Director and OEM provided consistent metadata'
            ' for new firmware,')
        print(' mirrors we contacted provided only untrustworthy images. ')
        print(GREEN + 'We have rejected these. Firmware not updated.\n' + ENDCOLORS)

    else:
      assert(os.path.exists(full_fname)), 'Programming error: no download ' + \
          'error, but file still does not exist.'
      print(GREEN + 'Successfully downloaded a trustworthy ' + repr(filepath) +
          ' image.' + ENDCOLORS)

      # If this is our firmware, "install".
      if filepath.startswith('/') and filepath[1:] == firmware_filename or \
        not filepath.startswith('/') and filepath == firmware_filename:

        print()
        print(GREEN + 'Provided firmware "installed"; metadata for this new '
            'firmware is stored for reporting back to the Director.' + ENDCOLORS)
        print()
        current_firmware_fileinfo = target




  # All targets have now been downloaded.

  if not len(verified_target_filepaths):
    print(YELLOW + 'No updates are required: the Director and OEM did'
        ' not agree on any updates.' + ENDCOLORS)
    return

  # # If we get here, we've tried all filepaths in the verified targets and not
  # # found something matching our expected firmware filename.
  # print('Targets were provided by the Director and OEM and were downloaded, '
  #     'but this Secondary expects its firmware filename to be ' +
  #     repr(firmware_filename) + ' and no such file was listed.')
  return





def generate_signed_ecu_manifest():

  global secondary_ecu
  global most_recent_signed_ecu_manifest

  # Generate and sign a manifest indicating that this ECU has a particular
  # version/hash/size of file2.txt as its firmware.
  most_recent_signed_ecu_manifest = secondary_ecu.generate_signed_ecu_manifest()





def ATTACK_send_corrupt_manifest_to_primary():
  """
  Attack: MITM w/o key modifies ECU manifest.
  Modify the ECU manifest without updating the signature.
  """
  # Copy the most recent signed ecu manifest.
  import copy
  corrupt_signed_manifest = copy.copy(most_recent_signed_ecu_manifest)

  corrupt_signed_manifest['signed']['attacks_detected'] += 'Everything is great, I PROMISE!'

  print(YELLOW + 'ATTACK: Corrupted Manifest (bad signature):' + ENDCOLORS)
  print('   Modified the signed manifest as a MITM, simply changing a value:')
  print('   The attacks_detected field now reads "' + RED +
      repr(corrupt_signed_manifest['signed']['attacks_detected']) + ENDCOLORS)

  import xmlrpc.client # for xmlrpc.client.Fault

  try:
    submit_ecu_manifest_to_primary(corrupt_signed_manifest)
  except xmlrpc.client.Fault:
    print(GREEN + 'Primary REJECTED the fraudulent ECU manifest.' + ENDCOLORS)
  else:
    print(RED + 'Primary ACCEPTED the fraudulent ECU manifest!' + ENDCOLORS)
  # (Next, on the Primary, one would generate the vehicle manifest and submit
  # that to the Director. The Director, in its window, should then indicate that
  # it has received this manifest and rejected it because the signature isn't
  # a valid signature over the changed ECU manifest.)




def ATTACK_send_manifest_with_wrong_sig_to_primary():
  """
  Attack: MITM w/o key modifies ECU manifest and signs with a different ECU's
  key.
  """
  # Discard the signatures and copy the signed contents of the most recent
  # signed ecu manifest.
  import copy
  corrupt_manifest = copy.copy(most_recent_signed_ecu_manifest['signed'])

  corrupt_manifest['attacks_detected'] += 'Everything is great; PLEASE BELIEVE ME THIS TIME!'

  signable_corrupt_manifest = tuf.formats.make_signable(corrupt_manifest)
  uptane.formats.SIGNABLE_ECU_VERSION_MANIFEST_SCHEMA.check_match(
      signable_corrupt_manifest)

  # Attacker loads a key she may have (perhaps some other ECU's key)
  key2_pub = demo.import_public_key('secondary2')
  key2_pri = demo.import_private_key('secondary2')
  ecu2_key = uptane.common.canonical_key_from_pub_and_pri(key2_pub, key2_pri)
  keys = [ecu2_key]

  # Attacker signs the modified manifest with that other key.
  signed_corrupt_manifest = uptane.common.sign_signable(
      signable_corrupt_manifest, keys)
  uptane.formats.SIGNABLE_ECU_VERSION_MANIFEST_SCHEMA.check_match(
      signed_corrupt_manifest)

  #import xmlrpc.client # for xmlrpc.client.Fault

  try:
    submit_ecu_manifest_to_primary(signed_corrupt_manifest)
  except xmlrpc.client.Fault as e:
    print('Primary REJECTED the fraudulent ECU manifest.')
  else:
    print('Primary ACCEPTED the fraudulent ECU manifest!')
  # (Next, on the Primary, one would generate the vehicle manifest and submit
  # that to the Director. The Director, in its window, should then indicate that
  # it has received this manifest and rejected it because the signature doesn't
  # match what is expected.)





def register_self_with_director():
  """
  Send the Director a message to register our ECU serial number and Public Key.
  In practice, this would probably be done out of band, when the ECU is put
  into the vehicle during assembly, not through the Secondary or Primary
  themselves.
  """
  # Connect to the Director
  server = xmlrpc.client.ServerProxy(
    'http://' + str(demo.DIRECTOR_SERVER_HOST) + ':' +
    str(demo.DIRECTOR_SERVER_PORT))

  print('Registering Secondary ECU Serial and Key with Director.')
  server.register_ecu_serial(secondary_ecu.ecu_serial, secondary_ecu.ecu_key)
  print(GREEN + 'Secondary has been registered with the Director.' + ENDCOLORS)





def register_self_with_primary():
  """
  Send the Primary a message to register our ECU serial number.
  In practice, this would probably be done out of band, when the ECU is put
  into the vehicle during assembly, not by the Secondary itself.
  """
  # Connect to the Primary
  server = xmlrpc.client.ServerProxy(
    'http://' + str(demo.PRIMARY_SERVER_HOST) + ':' +
    str(demo.PRIMARY_SERVER_PORT))

  print('Registering Secondary ECU Serial and Key with Primary.')
  server.register_new_secondary(secondary_ecu.ecu_serial)
  print(GREEN + 'Secondary has been registered with the Primary.' + ENDCOLORS)





def enforce_jail(fname, expected_containing_dir):
  """
  DO NOT ASSUME THAT THIS TEMPORARY FUNCTION IS SECURE.
  """
  # Make sure it's in the expected directory.
  #print('provided arguments: ' + repr(fname) + ' and ' + repr(expected_containing_dir))
  abs_fname = os.path.abspath(os.path.join(expected_containing_dir, fname))
  if not abs_fname.startswith(os.path.abspath(expected_containing_dir)):
    raise ValueError('Expected a filename in directory ' +
        repr(expected_containing_dir) + '. When appending ' + repr(fname) +
        ' to the given directory, the result was not in the given directory.')

  else: 
    return abs_fname
