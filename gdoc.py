# Google Docs Interface for use in gdocsfs
# Author: Pranav Kumar <pmkumar@cmu.edu>
#
# Base64 encoding is used for content - Docs doesn't play well with escape chars
#
# We need both the Docs and Drive APIs - Docs for creating/editing files and
# Drive for deleting them. As a result, we need two credential files and
# service objects.


from __future__ import print_function
import base64
import pickle
import re
import os.path
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# If modifying these scopes, delete the pickled token files
SCOPES = ['https://www.googleapis.com/auth/drive']

# Credentials for docs and drive
CRED_DOCS = 'cred_docs.pickle'
CRED_DRIVE = 'cred_drive.pickle'

# Tokens for docs and drive
TOKEN_DOCS = 'token_docs.pickle'
TOKEN_DRIVE = 'token_drive.pickle'


# The ID of a sample document called Blank
DOCUMENT_ID = '1dRvSqJzTekzn_rY__8cnQ7B6w8QNnz94pmnsH8Ml3Iw'

# The service objects for Docs and Drive
SERVICE = None
DRIVE_SERVICE = None

# Docs is 1-indexed... have to add 1 to all write indices
WRITE_OFFSET = 1

###############
### HELPERS ###
###############

# byte array -> string representation
def bytes_to_string(byte_seq):
    result = ''
    for b in byte_seq:
        result += f'{str(b)},'
    return result

# string rep -> byte array
def string_to_bytes(string):
    split = string.split(',')
    return bytes(int(s) for s in split if s.isdigit())
    # decoded_bytes = base64.b64decode(b64)
    # decoded_str = str(decoded_bytes, 'utf-8')
    # return decoded_str

######################
### INITIALIZATION ###
######################

def init_service_docs():
    """Initializes Docs API Service"""
    global SERVICE

    creds = None
    # The file token_docs.pickle stores the user's access and refresh tokens,
    # and is created automatically when the authorization flow completes for the
    # first time.
    if os.path.exists(TOKEN_DOCS):
        with open(TOKEN_DOCS, 'rb') as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CRED_DOCS, SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(TOKEN_DOCS, 'wb') as token:
            pickle.dump(creds, token)

    SERVICE = build('docs', 'v1', credentials=creds)

def init_service_drive():
    """Initializes Drive API Service"""
    global DRIVE_SERVICE

    creds = None
    # The file token_drive.pickle stores the user's access and refresh tokens,
    # and is created automatically when the authorization flow completes for the
    # first time.
    if os.path.exists(TOKEN_DRIVE):
        with open(TOKEN_DRIVE, 'rb') as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CRED_DRIVE, SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(TOKEN_DRIVE, 'wb') as token:
            pickle.dump(creds, token)

    DRIVE_SERVICE = build('drive', 'v3', credentials=creds)

# Initialize services
def initialize():
    init_service_docs()
    init_service_drive()

###########################
### READING AND WRITING ###
###########################

# Parses one paragraph element and gets all text
# Adapted from: https://developers.google.com/docs/api/samples/extract-text
def read_paragraph_element(element):
    """Returns the text in the given ParagraphElement.

        Args:
            element: a ParagraphElement from a Google Doc.
    """
    text_run = element.get('textRun')
    if not text_run:
        return ''
    return text_run.get('content')

# Parses document and reads num_bytes bytes starting at offset
# Adapted from: https://developers.google.com/docs/api/samples/extract-text
# Returns tuple: (byte array representing content, length of document content)
def read_strucutural_elements(elements, offset, num_bytes=None):

    # There should only be one paragraph
    assert(len(elements) == 1)
    elem = elements[0]
    paras = elem.get('paragraph')
    elems = paras.get('elements')

    # There should only be one element per paragraph
    assert(len(elems) == 1)
    text = read_paragraph_element(elems[0])
    total_content_len = len(text)

    # Get rid of newlines
    text = re.sub('[\n]', '', text)

    # Convert to array of bytes
    byte_seq = string_to_bytes(text)
    assert(text == bytes_to_string(byte_seq))

    if num_bytes:
        return byte_seq[offset : offset + num_bytes], total_content_len
    else:
        return byte_seq, total_content_len

# Args: doc id (string), offset (int), num_bytes (int/None)
#
# Reads num_bytes bytes of doc starting from offset
# (If num_bytes is None, reads the whole file by default)
#
# Returns tuple: (contents as byte array, length of content in doc)
def read_doc(doc_id, offset, num_bytes=None):
    global SERVICE

    # Get document
    document = SERVICE.documents().get(documentId=doc_id).execute()

    # Read all elements
    elements = document.get('body').get('content')

    # The first element is always a null element which doesn't matter
    elements = elements[1:]
    # contents: byte array
    contents, total_len = read_strucutural_elements(elements, offset, num_bytes)

    # Get the sequence of bytes by splitting on the comma

    return contents, total_len

# Args: doc id (string), offset (int), content to write (byte-string)
#
# Writes given content to specified doc at given offset
def write_doc(doc_id, offset, content):
    global SERVICE

    # Since we store in base64, offset must be mapped too. Most straightforward
    # way to do this is to read the doc, insert the string at the offset, then
    # write it back in

    # current_contents: byte array
    current_contents, total_content_len = read_doc(doc_id, 0, None)

    # Insert the contents at offset in current contents
    new_contents = current_contents[:offset] + content +\
        current_contents[offset:]

    # Clear all existing contents
    delete = {
        'deleteContentRange': {
            'range': {
                'startIndex': WRITE_OFFSET,
                'endIndex': total_content_len
            }
        }
    }

    # Encode new contents to string form
    byte_str = bytes_to_string(new_contents)

    # No empty bytes
    assert(',,' not in byte_str)

    # Insert new contents
    insert = {
        'insertText': {
            'location': {
                'index': WRITE_OFFSET,
            },
            'text': byte_str
        }
    }

    # Don't delete anything if the file is blank
    requests = [ delete ] if total_content_len > 1 else []
    if byte_str: requests.append(insert)

    # If any deletion or insertion needs to be performed
    if requests:
        result = SERVICE.documents().batchUpdate(
            documentId=doc_id, body={'requests': requests}).execute()

#############################
### CREATION AND DELETION ###
#############################

# Creates doc with given title and contents
# Returns created document ID
def create_doc(title, contents=None):
    global SERVICE

    # Construct document
    doc = {
        'title': title,
    }

    # Create the document
    doc_obj = SERVICE.documents().create(body=doc).execute()
    doc_id = doc_obj.get('documentId')

    # Write to it if contents is not None
    if contents:
        write_doc(doc_id, 0, contents)

    return doc_id

# Deletes document with given document ID
def delete_doc(doc_id):
    global DRIVE_SERVICE

    DRIVE_SERVICE.files().delete(fileId=doc_id).execute()
