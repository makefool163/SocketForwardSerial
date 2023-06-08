""" This is an incredibly simple port forwarder from port 7000 to 22 on
localhost.  It calls a callback function when the socket is closed, to
demonstrate one way that you could start to do interesting things by
starting from a simple framework like this.
"""

import eventlet


def closed_callback():
    print("called back")


def c_2_s_forward(source, dest, cb=lambda: None):
    """Forwards bytes unidirectionally from source to dest"""
    while True:
        d = source.recv(32384)
        if d == '':
            cb()
            break
        dest.sendall(d)
        print ("c_s: \t",len(d), end="\t\t")

def s_2_c_forward(source, dest, cb=lambda: None):
    """Forwards bytes unidirectionally from source to dest"""
    while True:
        d = source.recv(32384)
        if d == '':
            cb()
            break
        dest.sendall(d)
        print ("s_c: \t",len(d))

listener = eventlet.listen(('localhost', 13333))
while True:
    client, addr = listener.accept()
    server = eventlet.connect(('localhost', 22))
    # two unidirectional forwarders make a bidirectional one
    eventlet.spawn_n(c_2_s_forward, client, server, closed_callback)
    eventlet.spawn_n(s_2_c_forward, server, client)
