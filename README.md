# SocketForwardSerial
**1. Summary**

Forward socket service to another computer via a serial port.  
This project is Not like socat or netcat, which can only forward one connect to host, and when the connect is closed, it shall be unused.  
This project can allow multi-connects to socket server through one serial channel, and each connection will not affect each other.  
When some connects are closed, the channel can wait other connection is initiated.

**2. How to use**

You can run socket2ser.py to set its work in the source or targer. Indeed, only need a program that can run in the server and client both side and to do different functions. Because most base function is same in both side.  
Start the client and server side regardless of the order, of course, must be started both, and you can start a new socket connection.

usage: socket2ser.py [-h] [-ip IP] -port PORT -com COM [-baudrate BAUDRATE] [-d {0,1,2,3}] [-b] {S,C}
Forward socket service to another computer via a serial port.

positional arguments:
  {S,C}                 act as forwarding Server or Client

options:
  -h, --help            show this help message and exit
  -ip IP                Connect to Server IP when act as Source, default is localhost
  -port PORT            Connect to Server port when act as source/Listen port when act as target, default is 22
  -com COM              Serial Port
  -baudrate BAUDRATE    Serial Port baudrate
  -d {0,1,2,3}, --debug {0,1,2,3}
                          set debug out
  -b, --backdoor        set backdoor debug
    
  **3. Speical**
    
  3.1 A Gui Interface
  
  In addition to basic console versions of the program, I also write a GUI version of the program. You can run 'gui-s2s.py', it's based tkinter, the base interface (gui-s2s.ui) is build by pygubu-designer (I like it very much).
 
  3.2 Others
  
  This program used eventlet and pyserial lib package to do some green threads, so you must install evenlet by "pip install eventlet pyserial" or "conda install eventlet pyserial".
  I used eventlet lib package for long ago, it's very smart and lightweight.
  I just test all programe in windows, so when you use it in other os sys, you must try your work.

  3.3 TODO
  
  I will rewrite the console program by "GO", and I have not used "GO" any more.
