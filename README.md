# gDocsFS

Linux filesystem with a Google Docs backend, built using FUSE

## Instructions

Enable the Google Drive and Google Docs APIs for the desired account at:
* https://developers.google.com/drive/api/v3/quickstart/js
* https://developers.google.com/docs/api/quickstart/js

Click on the `Enable API` button in Step 1 of the above links.

Download the credential files as `cred_drive.json` and `cred_drive.json`

Run `python3 gdocsfs.py <mount location>` to mount the file system at the desired location

## Libraries
* `fusepy`
* `google-api-python-client`
* `google-auth-httplib2`
* `google-auth-oauthlib`