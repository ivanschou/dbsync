#!/opt/local/bin/python

# system imports
import os, sys, re, hashlib, math, datetime, time, ConfigParser
from collections import OrderedDict
from collections import defaultdict
from pprint import pprint

# globals
DROPBOX_HASH_CHUNK_SIZE = 4*1024*1024

cfg_file = os.environ['HOME'] + '/.dbsync'
cfg_changed = False;

# classes
class MultiOrderedDict(OrderedDict):
    def __setitem__(self, key, value):
        if isinstance(value, list) and key in self:
            self[key].extend(value)
        else:
            super(MultiOrderedDict, self).__setitem__(key, value)

cfg = ConfigParser.RawConfigParser(dict_type=MultiOrderedDict,
                                   allow_no_value=True )
cfg.optionxform=str

#functions
def tree():
    return defaultdict(tree)

def dicts(t): return { k: dicts(t[k]) for k in t }

def add( t, path ):
    for node in path.split(os.sep):
        t = t[node]

def test_node( t, path ):
    for node in os.path.dirname(path).split(os.sep):
        if t[node] != None:
            t = t[node]
    if os.path.basename(path) in t:
        return True
    else:
        return False

def get_config( section, key ):
    if cfg.has_section( section ):
        if cfg.has_option( section, key ):
            return cfg.get( section, key )
        else:
            return ''
    else:
        return ''

def set_config( section, key, value, is_comment = False ):
    global cfg
    global cfg_changed
    if not cfg.has_section( section ):
        cfg.add_section( section )
        cfg_changed=True
    if not is_comment and cfg.has_option( section, key ):
        cfg.remove_option( section, key )
    if not is_comment:
        cfg.set( section, key, value )
        cfg_changed=True
    else:
        comment = "; " + key
        if value != None:
            comment = comment + " = " + value
            cfg.set( section, comment )
            cfg_changed=True

def write_config():
    global cfg_file
    if cfg_changed:
        with open(cfg_file, 'w') as fp:
            cfg.write(fp)

def compute_dropbox_hash(filename):
    file_size = os.stat(filename).st_size
    num_chunks = int(math.ceil(file_size/DROPBOX_HASH_CHUNK_SIZE))

    with open(filename, 'rb') as f:
        block_hashes = b''
        while True:
            chunk = f.read(DROPBOX_HASH_CHUNK_SIZE)
            if not chunk:
                break
            block_hashes += hashlib.sha256(chunk).digest()
        return hashlib.sha256(block_hashes).hexdigest()

def make_enclosing( filename ):
    if not os.path.exists(os.path.dirname(filename)):
        try:
            os.makedirs(os.path.dirname(filename))
        except OSError as exc: # Guard against race condition
            if exc.errno != errno.EEXIST:
                raise

def recourse_directory( remote, function ):
    global dirs
    response = dbx.files_list_folder( remote, recursive=True, 
                                      include_deleted=True )
    for entry in response.entries:
        function ( entry )
#        if not isinstance( entry, dropbox.files.DeletedMetadata ):
        add( dirs, entry.path_display.lower() )
        while response.has_more:
            response = dbx.files_list_folder_continue( response.cursor )
            for entry in response.entries:
                function ( entry )
#                if not isinstance( entry, dropbox.files.DeletedMetadata ):
                add( dirs, entry.path_display.lower() )

def list_directory ( remote, function ):
    response = dbx.files_list_folder( remote )
    for entry in response.entries:
        function ( entry )
    while response.has_more:
        response = dbx.files_list_folder_continue( response.cursor )
        for entry in response.entries:
            function ( entry )

def cfg_add_directory( entry ):
    global cfg_changed
    if isinstance( entry, dropbox.files.FolderMetadata ):
        set_config( 'Remote Directories', 'Directory',
                    entry.path_display.decode('ascii'), True )

def download_entry ( entry, local_path ):
    print ( 'Downloading "' + entry.path_display + '"' ).encode('utf-8')
    try:
        md, res = dbx.files_download( entry.path_lower )
    except dropbox.exceptions.HttpError as err:
        print("Failed to download %s\n%s" % ( entry.path_display, err))    
        return None
    with open ( local_path, 'wb' ) as outfp:
        outfp.write( res.content )
        outfp.close()

def upload_entry ( entry, local_path, overwrite = True ):
    upload_file( entry.path_display, local_path, overwrite )

def upload_file ( remote_path, local_path, overwrite = True ):
    print ( 'Uploading "' + remote_path + '"' ).encode('utf-8')
    try:
        mode = (dropbox.files.WriteMode.overwrite
                if overwrite
                else dropbox.files.WriteMode.add)
        mtime = os.path.getmtime(local_path)
        file_size = os.path.getsize(local_path)
        if file_size <= DROPBOX_HASH_CHUNK_SIZE:
            with open( local_path, 'rb') as f:
                data = f.read()
            res = dbx.files_upload( data, remote_path, mode,
                client_modified=datetime.datetime(*time.gmtime(mtime)[:6]),
                                    mute=True)
        else:
            f = open( local_path, 'rb')
            upload_session_start_result = dbx.files_upload_session_start(f.read(DROPBOX_HASH_CHUNK_SIZE))
            cursor = dropbox.files.UploadSessionCursor(session_id=upload_session_start_result.session_id, offset=f.tell())
            commit = dropbox.files.CommitInfo(path=remote_path)

            while f.tell() < file_size:
                if ((file_size - f.tell()) <= DROPBOX_HASH_CHUNK_SIZE):
                    print dbx.files_upload_session_finish(f.read(DROPBOX_HASH_CHUNK_SIZE),
                                                          cursor,
                                                          commit)
                else:
                    dbx.files_upload_session_append(f.read(DROPBOX_HASH_CHUNK_SIZE),
                                                    cursor.session_id,
                                                    cursor.offset)
                    cursor.offset = f.tell()

    except dropbox.exceptions.ApiError as err:
        print("Failed to upload %s\n%s" % ( remote_path, err))
        return None

def updown_entry ( entry, local_path, overwrite = True ):
    local_hash = compute_dropbox_hash( local_path )
    if local_hash != entry.content_hash.decode('ascii'):
        lmtime = datetime.datetime.fromtimestamp(os.path.getmtime(local_path))
        if lmtime > entry.server_modified:
            upload_entry ( entry, local_path, overwrite )
        elif lmtime < entry.server_modified:
            download_entry ( entry, local_path )

def dump_entry ( entry ):
    print entry
    
def sync_entry ( entry ):
    global local_dir
    global dbx
    local_path = unicode(local_dir) + entry.path_display

    # remote file deleted but local file exists => prompt user
    if isinstance( entry, dropbox.files.DeletedMetadata ) and os.path.exists( local_path ):
        answer = input( entry.path_display.encode('ascii') + ' deleted. \n(D)elete local, (U)pload local, Do (N)othing: ')
        if len(answer) == 0:
            answer = 'n'
        if answer.lower()[0] == 'd':
            os.remove( local_path )
        elif answer.lower()[0] == 'u':
            upload_entry ( entry, local_path )
        # else do nothing

    # remote file exists but local file doesn't exist => download remote
    elif isinstance( entry, dropbox.files.FileMetadata ) and not os.path.exists( local_path ):
        make_enclosing( local_path )
        download_entry( entry, local_path )

    # compare local and remote hashes and sync newer if different
    elif isinstance( entry, dropbox.files.FileMetadata ) and os.path.exists( local_path ):
        updown_entry( entry, local_path )

def recourse_local( subdirectory ):
    global local_dir
    global dbx
    global dirs

    # finally check for local files that aren't represented in remote and upload
    for root, subdirs, files in os.walk(local_dir + subdirectory):
        if not os.path.basename(root).startswith('.'):
            for file in files:
                if not os.path.basename(file).startswith('.') and not os.path.basename(file).startswith('Icon\r'):
                    local_path = unicode(root) + os.sep + unicode(file)
                    remote_path = unicode(root[len(local_dir):]) + os.sep + unicode(file)
                    if not test_node( dirs, remote_path.lower() ):
                        upload_file( remote_path, local_path )
                

def config( ):
    if os.path.isfile(cfg_file):
        cfg.read(cfg_file)
    else:
        pass

    return;

# program flow begins here

if sys.version.startswith('2'):
    input = raw_input  # noqa: E501,F821; pylint: disable=redefined-builtin,undefined-variable,useless-suppression

# locate configuration
config()

# dropbox imports
import dropbox, requests, urllib
 
access_token=get_config( 'Auth', 'access_token' )
APP_KEY=get_config( 'Auth', 'app_key' )
APP_SECRET=get_config( 'Auth', 'app_secret' )

if APP_KEY == '':
    set_config( 'Auth', 'app_key', 'your_app_key', True )
if APP_SECRET == '':
    set_config( 'Auth', 'app_secret', 'your_app_secret', True )

if  APP_KEY == '' or APP_SECRET == '':
    print 'Please obtain an app key and secret from'
    print 'https://www.dropbox.com/developers/apps'
    write_config()
    sys.exit(0)

if len(access_token) == 0:
    auth_flow = dropbox.DropboxOAuth2FlowNoRedirect(APP_KEY, APP_SECRET)
    authorize_url = auth_flow.start()
    print "1. Go to: " + authorize_url
    print "2. Click \"Allow\" (you might have to log in first)."
    print "3. Copy the authorization code."
    auth_code = raw_input("Enter the authorization code here: ").strip()
    try:
        oauth_result = auth_flow.finish(auth_code)
        access_token=oauth_result.access_token
        set_config( 'Auth', 'access_token', access_token )
        
    except Exception, e:
        print('Error: %s' % (e,))
if len(access_token) == 0:
    write_config()
    sys.exit()
dbx = dropbox.Dropbox(access_token)

# Account info
#print dbx.users_get_current_account()

if not cfg.has_section( 'Local Directory' ):
    cfg.add_section( 'Local Directory' )
    local_dir = os.getcwd() + "/Dropbox"
    set_config( 'Local Directory', 'Directory', local_dir )
else:
    local_dir = cfg.get( 'Local Directory', 'Directory' )

if not os.path.exists(local_dir):
    os.makedirs(local_dir)

if cfg.has_section( 'Remote Directories' ):

    if cfg.has_option( 'Remote Directories', 'Directory' ):

        dirs = tree()

        for remote in cfg.get( 'Remote Directories',
                               'Directory' ).splitlines():
            recourse_directory( remote, sync_entry )
            recourse_local( remote )

            

    else:
        print 'No directories selected to sync.  Please edit .dbsync'

    pass

else:
    cfg.add_section( 'Remote Directories' )
    list_directory ( '', cfg_add_directory )

write_config()

print 'Dropbox sync completed.'
