# SocketForwardSerial
**1. Summary**

Forward socket service to another computer via a serial port.  
This program is Not like socat or netcat, which can only forward one connect to host, and when the connect is closed, it shall be unused.  
It can allow mulit-connect to socket server through one serial channel, and each connection will not affect each other.  
When some connects are closed, the channel can wait other connection is initiated.

**2. How to use**

You can run ser2socket.py to set its work in the source or targer. Indeed, only need a program that can run in the server and client both side and to do different functions. Because most base function is same in both side.  
Start the client and server side regardless of the order, of course, must be both starts, and you can start a new socket connection.

usage: ser2socket.py [-h] [-ip IP] -port PORT -com COM [-baudrate BAUDRATE] -d {S,T}  
Forward socket service to another computer via a serial port.  
positional arguments:  
  {S,T}               act as forwarding Source or Target  
options:  
  -h, --help          show this help message and exit    
  -ip IP              Connect to Server IP when act as Source, default is localhost.    
  -port PORT          Connect to Server port when act as source/Listen port when act as target, default is 22    
  -com COM            Serial Port    
  -baudrate BAUDRATE  Serial Port baudrate  
  -d, --debug         set debug out
  
  **3. Speical**
  
  
  This program used eventlet and pyserial lib package to do some green threads, so you must install evenlet by "pip install eventlet pyserial" or "conda install eventle pyserial".    
  I used eventlet lib package for long ago, it's very smart and lightweight.
