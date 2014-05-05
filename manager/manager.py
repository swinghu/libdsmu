import os
import socket
from threading import Lock
from threading import Thread
import time
import operator

PORT = 4444
NUMPAGES = 1000000
MAXCONNREQUESTS = 5

# PERMISSION TYPES
NONE = "NONE"
READ = "READ"
WRITE = "WRITE"

class PageTableEntry:
  def __init__(self):
    self.lock = Lock()
    self.users = []
    self.current_permission = NONE
    self.invalidate_confirmations = {}
    self.b64_encoded_page = "EXISTING"

class ManagerServer:
  def __init__(self, port, numPages):
    self.port = port
    self.clients = {} # client ids => ip addresses
    self.page_table_entries = [PageTableEntry() for i in range(numPages)]
    self.serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

  def Listen(self):
    self.serverSocket.bind(('localhost', self.port))
    self.serverSocket.listen(MAXCONNREQUESTS)
    # MAXCONNREQUESTS represents the number of outstanding clients waiting to
    # interact with the server before clients are turned away. It is 5 because
    # that is the normal default, but setting it to the # of clients is ok too.
    print "[Manager Server] Waiting..."

    while True:
      # A client exists as long as the ManagerServer has a TCP connection to it.
      # Therefore, when a client connects here, we make a new thread to handle
      # its requests.
      (clientSocket, address) = self.serverSocket.accept()
      print "[Manager] Accepted client with address: " + str(address)

      # Here, we just make a new thread to handle this client and run it, and
      # get back to waiting for new clients.
      clientThread = Thread(target = self.HandleClient, args = (clientSocket, ))

      client = clientSocket.getpeername()
      print "[Manager] Client id " + str(client)
      self.AddClient(client, clientSocket)

      clientThread.start()


  # pass requests along to correct method in a new thread
  # serve Add/Remove clients requests
  # serve RequestPage requests
  # receive invalidate/sendpage confirmations
  # Call appropriate method in a new thread
  def HandleClient(self, clientSocket):
    # running in a new thread, handle the client
    client = clientSocket.getpeername()
    while True:

      try:
        data = clientSocket.recv(7000) # Receive simple data, 4096 bytes here
        if not data: break
      except:
        break

      print "[Manager] " + data
      thread = Thread(target = self.ProcessMessage, args = (client, data))
      thread.start()

    clientSocket.close()


  def ProcessMessage(self, client, data):
    args = data.split(" ")

    if args[0] == "REQUESTPAGE":
      self.RequestPage(client, int(args[2]) % NUMPAGES, args[1])
    elif args[0] == "INVALIDATE":
      b64_encoded_data = args[3] if len(args) > 3 else ""
      self.InvalidateConfirmation(client, int(args[2]) % NUMPAGES, b64_encoded_data)
    else:
      print "FUCK BAD PROTOCOL"


  def AddClient(self, client, socket):
    self.clients[client] = socket

  def Invalidate(self, client, pagenumber, getpage):
    # Tell clients using the page to invalidate, wait for confirmation
    page_table_entry = self.page_table_entries[pagenumber]
    page_table_entry.invalidate_confirmations = {}

    for user in page_table_entry.users:
      if user != client:
        page_table_entry.invalidate_confirmations[user] = False

    for user in page_table_entry.users:
      if user != client:
        if getpage:
          self.clients[user].send("INVALIDATE " + str(pagenumber) + " PAGEDATA")
        else:
          self.clients[user].send("INVALIDATE " + str(pagenumber))

    while not reduce(operator.and_, page_table_entry.invalidate_confirmations.values(), True):
      time.sleep(.1)

    # When all have confirmed, return

  def InvalidateConfirmation(self, client, pagenumber, data):
    # Alert invalidate thread
    page_table_entry = self.page_table_entries[pagenumber]
    page_table_entry.invalidate_confirmations[client] = True

    if data:
      page_table_entry.b64_encoded_page = data

  def SendConfirmation(self, client, pagenumber, permission, b64_encoded_page):
    socket = self.clients[client]
    socket.send("REQUESTPAGE " + permission + " CONFIRMATION " + str(pagenumber) + " " + str(b64_encoded_page))

  def RequestPage(self, client, pagenumber, permission):
    # Invalidate page with other clients (if necessary)
    # Make sure client has latests page, ask other client to send page if necessary
    page_table_entry = self.page_table_entries[pagenumber]
    page_table_entry.lock.acquire()

    # Initial use of page FAULT HANDLER
    if page_table_entry.current_permission == NONE:
      page_table_entry.current_permission = permission
      page_table_entry.users = [client]
      self.SendConfirmation(client, pagenumber, permission, page_table_entry.b64_encoded_page)

      if permission == READ:
        page_table_entry.users= [client]

      page_table_entry.lock.release()
      return

    # READ FAULT HANDLER
    if permission == READ:
      if page_table_entry.current_permission == WRITE:
        self.Invalidate(client, pagenumber, True)
        page_table_entry.users = [client]
      else:
        page_table_entry.users.append(client)

    # WRITE FAULT HANDLER
    if permission == WRITE:
      if page_table_entry.current_permission == WRITE:
        self.Invalidate(client, pagenumber, True)
      else:
        self.Invalidate(client, pagenumber, False)
      page_table_entry.users = [client]

    self.SendConfirmation(client, pagenumber, permission, page_table_entry.b64_encoded_page)
    page_table_entry.current_permission = permission
    page_table_entry.lock.release()

if __name__ == "__main__":
  try:
    manager = ManagerServer(PORT, NUMPAGES)
    manager.Listen()
  except KeyboardInterrupt:
    for c, s in manager.clients.iteritems():
      s.close()
    os._exit(0)

