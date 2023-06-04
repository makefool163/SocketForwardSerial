# SocketForwardSerial
1. Summary

Forward socket service to another computer via a serial port

This programe is Not like socat or netcat, which can only forward one connect to host, and when the connect is closed, it shall unused.

It can allow mulit-connect to socket server through one serial channel, and each connection will not affect each other.

When one connect is closed, the channel can wait other connections is initiated.

2. How to use

You can run ser2socket.py to set its work in the source or targer. Indeed, only need a program that can run in the server and client both side and to do different functions. Because most base function is same in both side.

usage: ser2socket.py [-h] [-ip IP] -port PORT -com COM [-baudrate BAUDRATE] {S,T}

Forward socket service to another computer via a serial port.

positional arguments:
  {S,T}               act as forwarding Source or Target

options:
  -h, --help          show this help message and exit
  -ip IP              Connect to Server IP when act as Source, default is localhost.
  -port PORT          Connect to Server port when act as source/Listen port when act as target, default is 22
  -com COM            Serial Port
  -baudrate BAUDRATE  Serial Port baudrate
