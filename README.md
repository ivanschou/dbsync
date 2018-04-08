# dbsync
DropBox Python Sync Client

A Python script that syncs a local directory with DropBox.

You will need to get the DropBox Python API v2 from git://github.com/dropbox/dropbox-sdk-python.git

You will need to get your own app key from https://www.dropbox.com/developers/apps

The script uses OAUTH to log into your DropBox.  Do not loose your authentication token.  You will have to recreate your app if you need to get a new token

After running the script once, edit the ${HOME}/.dbsync configuration file and enter your app key and app secret.

Run the script again to obtain an authentication token and retrieve a list of top-level directories in your DropBox.

Edit the ${HOME}/.dbsync again and select the subdirectories that you would like to sync.  Change the local DropBox location as desired.  An empty one will be created in the current working directory.  If that's not the desired location, you will need to move or delete the empty directory

Known Issues

Currently, this script doesn't track local filesystem deletions or moves.  You will be responsible for deleting or moving files using the DropBox web site.
