# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function

# 串口数据流中 每个数据帧由 FF 开始
# FF 是特殊标识字符，如果在 负载数据中有 FF，则用 连续的两个 FF 代替，即 FF FF = FF 实际字符
# 遇到 一个 FF，就说明是数据帧的 开始
# 1. 连接、断开 指示数据帧
#    FF FE XX YY  
# （负载数据中万一出现 FF FE 这种情况，由于 FF 被 展开成了 FF FF， 
#   所以 必定是 FF FF FE，这样就避免了识别混淆问题)
#  (若 负载数据 最后一个字符是 FF，数据流将会是 FF FF FF FE 的情况，
#   即 FE 前面若有 偶数个 FF，说明是负载数据，若有奇数个 FF，说明是帧头数据)
#    XX是约定的连接序号
#  1) YY = 00 新连接发起, 
#    服务器端，连接成功后，则不回复，进入正常数据发送
#    新连接来的时候，XX要分配一个00~FD之间的序号，如果没有可分配的，就拒绝连接
#  2) YY = 01 若服务器端连接失败，则返回 FF FE XX 01
#  3) YY = 02 若网络连接（无论哪S/T端）断开，向对端发送 FF FE XX 02，通知对端相应的连接
# 2. 负载数据帧
#    FF XX ZZ ZZ (XX 不等于 FF 或 FE) ... FF XX 00 00
#    XX是约定的新连接序号，后面就是实际的数据包内容，
#    ZZ ZZ 是数据包长度
#    FF XX 00 00 是数据负载的帧尾，标识负载数据帧结束了

import eventlet
import serial
import queue
import struct
import argparse
from eventlet import tpool, backdoor
import socket

class SerialSocket(serial.Serial):
    def recv(self):
        # 等待
        data = tpool.execute(self.read, 1)
        # 读完
        while self.in_waiting:
            data += tpool.execute(self.read, self.in_waiting)
        return data

def com_listen_message():
    ss = SerialSocket("com10")
    buffer = b''
    while True:
        g = eventlet.spawn(ss.recv)
        data = g.wait()
        buffer +=data

class Socket2Ser_Base:
    def __init__(self, ip, port, com_port, baud_rate, debug=False):
        self.debug = debug
        self.ip = ip
        self.port = port
        self.com_port = com_port
        self.com = SerialSocket(port=com_port, timeout=None, baudrate=baud_rate)
        # baud_rate = 115200
        self.socket_pool = eventlet.queue.Queue() # socket连接序号的pool
        for i in range(0xFE):
            self.socket_pool.put(i)
        self.com_send_Queue = eventlet.queue.Queue() # com口等待发送queue
        self.com_recv_Queue = eventlet.queue.Queue() # com口输入queue，用以处理FF前导符
        self.net_send_Queue = eventlet.queue.Queue()
        self.socket_stock = {}
        self.com_in_status = True # False 正常传送状态, True 前导处理状态
        self.com_leading_packet_buf = b""
        self.com_sock_id_online = 0 
        self.pool = eventlet.GreenPool()
    def net_recv(self, sock, socket_id):
        while True:
            try:
                d = sock.recv(65535)
                print ("R\t", len(d), end="\t", flush=True)
            except Exception as e:
                # 对付可能的接收错误，特别是sock失效了
                # 当然可能是被主协程给关掉了
                if self.debug:
                    print (e)
                    # 测试结果的确是，在服务器端，主协程会关这个
                break
            # 重新组合数据，处理FF
            if len(d) > 0:
                # eventlet的sock.recv是阻塞模式
                # 1. 有实际数据来，阻塞会打开，返回实际数据
                # 2. 对端断开连接，阻塞也会打开，返回空数据
                d = d.replace(b"\xff",b"\xff\xff")
                d = b"\xff" + struct.pack("!BH", socket_id, len(d)) + d \
                    + b"\xff" + struct.pack("!B", socket_id) + b"\x00\x00"
                self.com_send_Queue.put(d)
            else:
                # 对端已断开连接
                # 要把这个中断信号传递到对端去... 
                # 如果是T端还好，告诉S端关闭对应的连接即可
                # 若是S端中断，说明S端的服务关掉了，啥都没有了
                # 总归老连接关闭，以后的新连接拒绝服务连接，直到S端的服务恢复
                print ("net_recv closed.")
                if socket_id in self.socket_stock:
                    # 字典pop不会被协程切走，先干为快
                    self.socket_stock.pop(socket_id)
                    # 下面的三行，应该有很严密的时间先后关系
                    # 因为在协程体系下，使可能被其他协程切换出去的
                    sock.close()
                    self.com_send_Queue.put(b"\xff\xfe" + struct.pack("!B", socket_id) + b"\x02")
                    self.socket_pool.put(socket_id)
                    # 通告对端，网络连接已经断了
                break
    def net_send(self):
        while True:
            id, buf = self.net_send_Queue.get(True)
            if id in self.socket_stock:
                sock = self.socket_stock[id]
                sock.send(buf)
                print ("S\t", len(buf), flush=True)
    def print_hex(self, buf, f):
        # 把输入的 bytes 打印成 16进制形式
        hex = ''
        for b in buf:
            hex += f + format(b, '02x')
        print (hex, end="", flush=True)
    def com_send(self):
        while True:
            buf = self.com_send_Queue.get(True)
            self.com.write(buf)
            if self.debug:
                self.print_hex(buf, "-")
    def com_recv(self):
        FF_Count = 0
        leading_packet = 0
        comOutBuf = b""
        while True:
            try:
                g = self.pool.spawn(self.com.recv)
                d = g.wait() # 协程读取com口
                if self.debug:
                    self.print_hex(d, "_")
                while len(d) > 0:
                    if leading_packet > 0:
                        leading_packet += 1
                        self.com_leading_packet_buf += d[0:1]
                        d = d[1:]
                        if leading_packet == 4:
                            leading_packet = 0
                            self.com_leading_packet_proc()
                    else:
                        if d[0] == 0xff:
                            FF_Count += 1
                            if FF_Count == 2:
                                comOutBuf += b"\xff"
                                FF_Count = 0
                                d = d[1:]
                        elif FF_Count == 0:
                            comOutBuf += d[0:1]
                            d = d[1:]
                        else:
                            # d[0] != 0xff and FF_Count == 1
                            # 此种情况，说明遇见 帧头数据 了
                            FF_Count = 0
                            self.com_leading_packet_buf = b"\xff" + d[0:1]
                            d = d[1:]
                            leading_packet = 2
                            if len(comOutBuf) > 0:
                                # 似乎有点问题，如果没有新的祯头，接收到的完整com数据负载就不外发？
                                # ....已用数据负载帧的结束帧尾标记解决此问题
                                self.net_send_Queue.put((self.com_sock_id_online, comOutBuf))
                                comOutBuf = b""
            except (SystemExit, KeyboardInterrupt):
                break
    def com_leading_packet_proc(self):
        if self.com_leading_packet_buf[1] != b"\xfe":
            # 说明是数据负载 帧
            self.com_sock_id_online = self.com_leading_packet_buf[1]
            self.com_leading_packet_buf = b""
        else:
            if self.com_leading_packet_buf[3] == 2:
                # 收到 对端 发来的连接已断开，则断开 己方 的连接
                sock_id = self.com_leading_packet_buf[2]
                if sock_id in self.socket_stock:
                    sock = self.socket_stock[sock_id]
                    sock.close()
            # 00 发起连接 操作指示，应该在 client 的子类中定义
            # 01 连接失败 操作指示，应该在 server 的子类中定义

        
class Socket2Ser_Client(Socket2Ser_Base):
    def Start(self):
        print ("self.ip", self.ip)
        server_sock = eventlet.listen((self.ip, self.port), reuse_addr = True, backlog=0xfe)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        # 启动alive探测
        server_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 20)
        # 空闲时间    
        server_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 3)
        # 探测间隔
        server_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        # 探测次数
        # 这样对端连接断开后，最少 29秒后，本端也会断开
        self.pool.spawn_n(self.com_recv)
        self.pool.spawn_n(self.com_send)        
        #pool.spawn_n(self.net_recv)
        # listen 的recv 只有被 accept 后，才会有
        self.pool.spawn_n(self.net_send)
        while True:
            try:
                print ("Start Listening accept wait...")
                new_sock, address = server_sock.accept()
                print("accepted", address, end=" ")
                try:
                    socket_id = self.socket_pool.get()
                    self.socket_stock[socket_id] = new_sock
                    out_str = b"\xff\xfe" + struct.pack("!B", socket_id) + b"\x00"
                    self.com_send_Queue.put(out_str)
                    self.pool.spawn_n(self.net_recv, new_sock, socket_id)                
                    # 启动网络 收报 协程
                    print ("accept success at: ", socket_id)
                except queue.Empty:
                    # 连接池已经空了，不能连接了
                    new_sock.close()
                    print ("accept fail.")
            except (SystemExit, KeyboardInterrupt):
                break
    def com_leading_packet_proc(self):
        if self.com_leading_packet_buf[1] == b"\xFE" \
            and self.com_leading_packet_buf[3] == b"\x01":
                # 运行在客户模式下：
                # 01服务器返回连接失败的处理
                id = struct.unpack("!B", self.com_Forward_buf[1])
                sock = self.socket_stock[id]
                # 不管 close 是否 成功, 先必须把前导符号消除，因为 close 的动作会进入协程切换状态
                self.com_leading_packet_buf = b""
                sock.close()
                # 此处可以不回收 id，断开后，在net_recv中会有处理
                # self.socket_pool.put(id)
        super().com_leading_packet_proc()

class Socket2Ser_Server(Socket2Ser_Base):
    def Start(self):
        #pool.spawn_n(self.com_recv)
        self.pool.spawn_n(self.com_send)        
        # pool.spawn_n(self.net_recv)
        # 只有从com发了连接信号后，才会去连接服务器，产生recv过程
        self.pool.spawn_n(self.net_send)
        self.com_recv() # 进入读取 com 口的循环
    def com_leading_packet_proc(self):
        #print ("buf:",self.com_leading_packet_buf)
        if self.com_leading_packet_buf[1] == b"\xFE" \
            and self.com_leading_packet_buf[3] == b"\x00":
            # 运行在服务器模式下：
            # 00 收到客户端的连接请求的处理
            print ("try fork ...", self.ip, self.port, end=" ")
            id = self.com_leading_packet_buf[2]
            # 不管 connect 是否 成功, 先必须把前导符号消除，因为 connect 的动作会进入协程切换状态
            self.com_leading_packet_buf = b""
            try:
                sock = eventlet.connect((self.ip, self.port))
                print ("fork a connect", end=" ")
                self.socket_stock[id] = sock
                print("accepted", id)
                self.pool.spawn_n(self.net_recv, sock, id)
                # 启动网络 收报 协程
            except:
                # 连接服务失败
                out_str = b"\xff\xfe" + struct.pack("!B", id) + b"\x01"
                self.com_send_Queue.put(out_str)
        super().com_leading_packet_proc()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Forward socket service to another computer via a serial port.")
    parser.add_argument('Action', choices=['S', 'T'], type=str, help='act as forwarding Source or Target')
    parser.add_argument('-ip', default='localhost', type=str, help="Connect to Server IP when act as Source, default is localhost")
    parser.add_argument('-port', default=22, type=int, nargs=1, required=True, help='Connect to Server port when act as source/Listen port when act as target, default is 22')
    parser.add_argument('-com', type=str, nargs=1, required=True, help="Serial Port")
    parser.add_argument('-baudrate', type=int, default=115200, help="Serial Port baudrate")
    parser.add_argument('-d', "--debug", action="store_true", help="set debug out")
    parser.add_argument('-b', "--backdoor", action="store_true", help="set backdoor debug")
    args = parser.parse_args()
    #print (args.port)

    if args.backdoor:
        eventlet.spawn(backdoor.backdoor_server, eventlet.listen(('localhost', 55555)), locals())
    if args.Action == "S":
        ss = Socket2Ser_Server(args.ip, args.port[0], args.com[0], args.baudrate, args.debug)
    else:
        ss = Socket2Ser_Client(args.ip, args.port[0], args.com[0], args.baudrate, args.debug)
    ss.Start()
