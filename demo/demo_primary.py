"""
demo_primary.py

Demonstration code handling a Primary client.


Use:

import demo.demo_primary as dp
dp.clean_slate() # also listens, xmlrpc
  At this point, separately, you will need to initialize at least one secondary.
  See demo_secondary use instructions.
dp.generate_signed_vehicle_manifest()
dp.submit_vehicle_manifest_to_director()




"""

import demo
import uptane
import uptane.common # for canonical key construction and signing
import uptane.clients.primary as primary
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


# Globals
_client_directory_name = 'temp_primary' # name for this Primary's directory
_vin = '111'
_ecu_serial = '11111'
firmware_filename = 'infotainment_firmware.txt'
current_firmware_fileinfo = {}
primary_ecu = None
ecu_key = None

director_proxy = None

listener_thread = None

most_recent_signed_vehicle_manifest = None


def clean_slate(
    use_new_keys=False,
    client_directory_name=_client_directory_name,
    vin=_vin,
    ecu_serial=_ecu_serial):
  """
  """

  global primary_ecu
  global _client_directory_name
  global _vin
  global _ecu_serial
  global listener_thread

  _client_directory_name = client_directory_name
  _vin = vin
  _ecu_serial = ecu_serial


  # Load the public timeserver key.
  key_timeserver_pub = demo.import_public_key('timeserver')

  # Generate a trusted initial time for the Primary.
  clock = tuf.formats.unix_timestamp_to_datetime(int(time.time()))
  clock = clock.isoformat() + 'Z'
  tuf.formats.ISO8601_DATETIME_SCHEMA.check_match(clock)

  # Load the private key for this Primary ECU.
  load_or_generate_key(use_new_keys)


  # Initialize a Primary ECU, making a client directory and copying the root
  # file from the repositories.
  primary_ecu = primary.Primary(
      full_client_dir=os.path.join(uptane.WORKING_DIR, _client_directory_name),
      pinning_filename=demo.DEMO_PINNING_FNAME,
      vin=_vin,
      ecu_serial=_ecu_serial,
      fname_root_from_mainrepo=demo.MAIN_REPO_ROOT_FNAME,
      fname_root_from_directorrepo=demo.DIRECTOR_REPO_ROOT_FNAME,
      primary_key=ecu_key,
      time=clock,
      timeserver_public_key=key_timeserver_pub)


  if listener_thread is None:
    listener_thread = threading.Thread(target=listen)
    listener_thread.setDaemon(True)
    listener_thread.start()
  print('\n' + GREEN + 'Primary is now listening for messages from ' +
      'Secondaries.' + ENDCOLORS)

  register_self_with_director()

  print(GREEN + '\n Now simulating a Primary that rolled off the assembly line'
      '\n and has never seen an update.' + ENDCOLORS)



def load_or_generate_key(use_new_keys=False):
  """Load or generate an ECU's private key."""

  global ecu_key

  if use_new_keys:
    demo.generate_key('primary')

  # Load in from the generated files.
  key_pub = demo.import_public_key('primary')
  key_pri = demo.import_private_key('primary')

  ecu_key = uptane.common.canonical_key_from_pub_and_pri(key_pub, key_pri)




def update_cycle():
  """
  """

  global primary_ecu
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
  primary_ecu.refresh_toplevel_metadata_from_repositories()


  # Get the list of targets the director expects us to download and update to.
  # Note that at this line, this target info is not yet validated with the
  # supplier repo: that is done a few lines down.
  directed_targets = primary_ecu.get_target_list_from_director()

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
        primary_ecu.get_validated_target_info(target_filepath))
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

  # TODO: Review the targets here and assign them to ECUs?
  # Or do after they're downloaded below?

  #for target in verified_targets
  # TODO: <~> CURRENTLY WORKING HERE


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
      primary_ecu.updater.download_target(target, full_targets_directory)

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


      # TODO: <~> Distribute this file to the appropriate Secondary:


      # # If this is our firmware, "install".
      # if filepath.startswith('/') and filepath[1:] == firmware_filename or \
      #   not filepath.startswith('/') and filepath == firmware_filename:

      #   print()
      #   print(GREEN + 'Provided firmware "installed"; metadata for this new '
      #       'firmware is stored for reporting back to the Director.' + ENDCOLORS)
      #   print()
      #   current_firmware_fileinfo = target




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





def generate_signed_vehicle_manifest():

  global primary_ecu
  global most_recent_signed_vehicle_manifest

  # Generate and sign a manifest indicating that this ECU has a particular
  # version/hash/size of file2.txt as its firmware.
  most_recent_signed_vehicle_manifest = \
      primary_ecu.generate_signed_vehicle_manifest()





def submit_vehicle_manifest_to_director(signed_vehicle_manifest=None):

  global most_recent_signed_vehicle_manifest

  if signed_vehicle_manifest is None:
    signed_vehicle_manifest = most_recent_signed_vehicle_manifest


  uptane.formats.SIGNABLE_VEHICLE_VERSION_MANIFEST_SCHEMA.check_match(
      signed_vehicle_manifest)
  # TODO: <~> Be sure to update the previous line to indicate an ASN.1
  # version of the ecu_manifest after encoders have been implemented.


  server = xmlrpc.client.ServerProxy(
      'http://' + str(demo.DIRECTOR_SERVER_HOST) + ':' +
      str(demo.DIRECTOR_SERVER_PORT))
  #if not server.system.listMethods():
  #  raise Exception('Unable to connect to server.')

  print("Submitting the Primary's manifest to the Director.")

  server.submit_vehicle_manifest(
      primary_ecu.vin,
      primary_ecu.ecu_serial,
      signed_vehicle_manifest)


  print(GREEN + 'Submission of Vehicle Manifest complete.' + ENDCOLORS)





def register_self_with_director():
  """
  Send the Director a message to register our ECU serial number and Public Key.
  """
  # Connect to the Director
  server = xmlrpc.client.ServerProxy(
    'http://' + str(demo.DIRECTOR_SERVER_HOST) + ':' +
    str(demo.DIRECTOR_SERVER_PORT))

  print('Registering Primary ECU Serial and Key with Director.')
  server.register_ecu_serial(primary_ecu.ecu_serial, primary_ecu.primary_key)
  print(GREEN + 'Primary has been registered with the Director.' + ENDCOLORS)



# This wouldn't be how we'd do it in practice. ECUs would probably be registered
# when put into a vehicle, directly rather than through the Primary.
# def register_secondaries_with_director():
#   """
#   For each of the Secondaries that this Primary is in charge of, send the
#   Director a message registering that Secondary's ECU Serial and public key.
#   """




# def ATTACK_send_corrupt_manifest_to_director():
#   """
#   Attack: MITM w/o key modifies ECU manifest.
#   Modify the ECU manifest without updating the signature.
#   """
#   # Copy the most recent signed ecu manifest.
#   corrupt_signed_manifest = {k:v for (k,v) in most_recent_signed_ecu_manifest.items()}

#   corrupt_signed_manifest['signed']['attacks_detected'] += 'Everything is great, I PROMISE!'
#   #corrupt_signed_manifest['signed']['ecu_serial'] = 'ecu22222'

#   print(YELLOW + 'ATTACK: Corrupted Manifest (bad signature):' + ENDCOLORS)
#   print('   Modified the signed manifest as a MITM, simply changing a value:')
#   print('   The attacks_detected field now reads ' + RED + '"Everything is great, I PROMISE!' + ENDCOLORS)

#   #import xmlrpc.client # for xmlrpc.client.Fault

#   try:
#     primary_ecu.submit_ecu_manifest_to_director(corrupt_signed_manifest)
#   except xmlrpc.client.Fault:
#     print(GREEN + 'Director service REJECTED the fraudulent ECU manifest.' + ENDCOLORS)
#   else:
#     print(RED + 'Director service ACCEPTED the fraudulent ECU manifest!' + ENDCOLORS)
#   # (The Director, in its window, should now indicate that it has received this
#   # manifest. If signature checking for manifests is on, then the manifest is
#   # rejected. Otherwise, it is simply accepted.)




# def ATTACK_send_manifest_with_wrong_sig_to_director():
#   """
#   Attack: MITM w/o key modifies ECU manifest and signs with a different ECU's
#   key.
#   """
#   # Discard the signatures and copy the signed contents of the most recent
#   # signed ecu manifest.
#   corrupt_manifest = {k:v for (k,v) in most_recent_signed_ecu_manifest['signed'].items()}

#   corrupt_manifest['attacks_detected'] += 'Everything is great; PLEASE BELIEVE ME THIS TIME!'

#   signable_corrupt_manifest = tuf.formats.make_signable(corrupt_manifest)
#   uptane.formats.SIGNABLE_ECU_VERSION_MANIFEST_SCHEMA.check_match(
#       signable_corrupt_manifest)

#   # Attacker loads a key she may have (perhaps some other ECU's key)
#   key2_pub = demo.import_public_key('secondary2')
#   key2_pri = demo.import_private_key('secondary2')
#   ecu2_key = uptane.common.canonical_key_from_pub_and_pri(key2_pub, key2_pri)
#   keys = [ecu2_key]

#   # Attacker signs the modified manifest with that other key.
#   signed_corrupt_manifest = uptane.common.sign_signable(
#       signable_corrupt_manifest, keys)
#   uptane.formats.SIGNABLE_ECU_VERSION_MANIFEST_SCHEMA.check_match(
#       signed_corrupt_manifest)

#   #import xmlrpc.client # for xmlrpc.client.Fault

#   try:
#     primary_ecu.submit_ecu_manifest_to_director(signed_corrupt_manifest)
#   except xmlrpc.client.Fault as e:
#     print('Director service REJECTED the fraudulent ECU manifest.')
#   else:
#     print('Director service ACCEPTED the fraudulent ECU manifest!')
#   # (The Director, in its window, should now indicate that it has received this
#   # manifest. If signature checking for manifests is on, then the manifest is
#   # rejected. Otherwise, it is simply accepted.)





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





# Restrict director requests to a particular path.
# Must specify RPC2 here for the XML-RPC interface to work.
class RequestHandler(xmlrpc.server.SimpleXMLRPCRequestHandler):
  rpc_paths = ('/RPC2',)


def listen():
  """
  Listens on PRIMARY_SERVER_PORT for xml-rpc calls to functions
  """

  # Create server
  server = xmlrpc.server.SimpleXMLRPCServer(
      (demo.PRIMARY_SERVER_HOST, demo.PRIMARY_SERVER_PORT),
      requestHandler=RequestHandler, allow_none=True)
  #server.register_introspection_functions()

  # # Register function that can be called via XML-RPC, allowing a Primary to
  # # submit a vehicle version manifest.
  # server.register_function(
  #     self.register_vehicle_manifest, 'submit_vehicle_manifest')

  # In the longer term, this won't be exposed: it will only be reached via
  # register_vehicle_manifest. For now, during development, however, this is
  # exposed.
  server.register_function(
      primary_ecu.register_ecu_manifest, 'submit_ecu_manifest')

  server.register_function(
      primary_ecu.register_new_secondary, 'register_new_secondary')

  print('Primary will now listen on port ' + str(demo.PRIMARY_SERVER_PORT))
  server.serve_forever()
