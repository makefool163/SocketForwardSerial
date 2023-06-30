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
# 此处 socket 模块的作用 是用来引入几个配置参数常量
import os
import re

class SerialSocket2(serial.Serial):
    def recv(self):
        # 等待
        data = tpool.execute(self.read, 1)
        # 读完
        while self.in_waiting:
            try:
                data += tpool.execute(self.read, self.in_waiting)
            except Exception as e:
                print (e)
        return data

class SerialSocket(serial.Serial):
    def recv(self):
        while True:
            if self.in_waiting > 0:
                data = self.read(self.in_waiting)
                return data
            else:
                eventlet.sleep(0)
                # 切换到其他协程去

def com_listen_message():
    ss = SerialSocket2("com10")
    buffer = b''
    while True:
        g = eventlet.spawn(ss.recv)
        data = g.wait()
        buffer +=data

class Socket2Ser_Base:
    def __init__(self, ip, port, com_port, baud_rate, debug=0, gui_debug=None, com_log=None):
        self.com_log = com_log
        if com_log != None:
            # 把log文件清一下零
            fsplit = os.path.splitext(self.com_log)
            fname_s = fsplit[0] + "_S"
            fname_r = fsplit[0] + "_R"
            if len(fsplit[1]) > 0:
                fname_s += fsplit[1]
                fname_r += fsplit[1]
            if os.path.exists(fname_s):
                os.remove (fname_s)
            if os.path.exists(fname_r):                
                os.remove (fname_r)

        self.Parent = "S"
        self.debug = debug
        self.gui_debug = gui_debug
        self.ip = ip
        self.port = port
        self.com_port = com_port
        self.baud_rate = baud_rate
        self.socket_pool = eventlet.queue.Queue() # socket连接序号的pool
        for i in range(0xFE):
            self.socket_pool.put(i)
        self.com_send_Queue = eventlet.queue.Queue() # com口等待发送queue
        #self.com_recv_Queue = eventlet.queue.Queue() # com口输入queue，用以处理FF前导符
        self.net_send_Queue = eventlet.queue.Queue()
        self.socket_stock = {}
        self.com_in_status = True # False 正常传送状态, True 前导处理状态
        self.com_leading_packet_buf = b""
        self.com_sock_id_online = 0 
        self.pool = eventlet.GreenPool()
    def Start(self):
        self.com = SerialSocket(port=self.com_port, timeout=None, baudrate=self.baud_rate)
    def Stop(self):
        print ("Stop Socket2Ser")
        try:
            self.com.close()
        except Exception as e:
            print (e)
        for sock_id in self.socket_stock:    
            try:        
                sock = self.socket_stock[sock_id]
                sock.close()
            except Exception as e:
                print (e)
        eventlet.sleep(2)
        # 稍等一下，让其他协程发现出错，完成退出动作
        # 好像也无必要，因为是协程状态，不存在释放资源的问题
    def net_recv(self, sock, socket_id):
        while True:
            try:
                if self.__class__ == "__main__.Socket2Ser_Server":
                    # 至少要保证一个方向优于另一个方向
                    # 这里就把客户往服务器的通信方向定义为优先方向
                    while (self.net_send_Queue.qsize() > 0):
                        eventlet.sleep(0.1)
                #d = sock.recv(65535)
                d = sock.recv(32768)
                eventlet.sleep(0)
                if self.debug >= 1:
                    print ("R\t", len(d), end="\t", flush=True)
                    if self.__class__ != "__main__.Socket2Ser_Client":
                        print ("")
                if self.gui_debug != None:
                    #print (self.gui_debug)
                    self.gui_debug ('r', str(socket_id)+"\t"+str(len(d)))
            except Exception as e:
                # 对付可能的接收错误，特别是sock失效了
                # 当然可能是被主协程给关掉了
                if self.debug >= 0:
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
                eventlet.sleep(0)
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
                if self.debug >= 1:
                    print ("S\t", len(buf), end="\t", flush=True)
                    if self.__class__ == "__main__.Socket2Ser_Client":
                        print ("")
                if self.gui_debug != None:
                    #print (self.gui_debug)
                    self.gui_debug ('s', str(id)+"\t"+str(len(buf)))
    def print_hex(self, buf, f):
        # 把输入的 bytes 打印成 16进制形式
        hex = ''
        for b in buf:
            hex += f + format(b, '02x')
        print (hex, end="", flush=True)
    def com_log_file(self, SC, buf):
        hex = ''
        for b in buf:
            hex += " " + format(b, "02x")

        fsplit = os.path.splitext(self.com_log)
        if SC == "S":
            fname = fsplit[0] + "_S"
        else:
            fname = fsplit[0] + "_R"
        if len(fsplit[1]) > 0:
            fname += fsplit[1]

        with open(fname, "a") as f:
            f.write(hex+"\n")
    def com_send(self):
        while True:
            buf = self.com_send_Queue.get(True)
            #if self.debug >= 0:
            #    print ("COM_S\t", len(buf), end="\t", flush=True)
            self.com.write(buf)
            eventlet.sleep(0)
            # 遇到大规模的数据发送情况下，给个hub切换的机会
            # 避免其他协程失去了控制
            if self.debug >= 2:
                self.print_hex(buf, "-")
            if self.com_log != None:
                self.com_log_file("S", buf)
    def com_recv(self):
        look_FF = False
        FF_Count = 0
        leading_packet = 0
        comOutBuf = b"" # 暂存还没有处理的串口接收数据
        while True:
            try:
                if self.__class__ == "__main__.Socket2Ser_Client":
                    while    (self.com_send_Queue.qsize() > 0 \
                           or self.net_send_Queue.qsize() > 0):
                        # 如果是客户端，就要优先发送端，保证服务器能尽快的了解客户的情况
                        # 至少要保证一个方向优于另一个方向
                        # 这里就把客户往服务器的通信方向定义为优先方向
                        eventlet.sleep(0.1)
                try:
                    """
                    g = self.pool.spawn(self.com.recv)
                    d = g.wait() # 协程读取com口
                    """
                    d = self.com.recv()
                except:
                    # 出现读错误，就跳出大循环，说明串口已经失败了
                    break
                if self.debug >= 2:
                    self.print_hex(d, "_")                    
                d = comOutBuf +d

                comOutBuf = b""
                sp_d = d.split(b"\xff")
                if sp_d[0] == b"":
                    # 若 0xff 是串的第一个，split会产生第一个空串
                    sp_d = sp_d[1:]
                # S--- 处理双连FF 
                i = 1
                while i < len(sp_d):
                    s = sp_d[i]
                    if len(s) == 0 and i+1 < len(sp_d):
                        # 双 FF 连串
                        sp_d[i-1] += b"\xff\xff" + sp_d[i+1]
                        sp_d.pop(i)
                        sp_d.pop(i)
                        i -= 1
                    i += 1
                sp_d = [b"\xff" +s for s in sp_d]
                # E--- 处理双连FF
                if d[0] != 0xff:
                    sp_d[0] = sp_d[0][1:]

                try:
                    for i, s in enumerate(sp_d[:-1]):
                        if s[1] == 0xFE:
                            self.com_leading_packet_buf = s
                            self.com_leading_packet_proc()
                        else:
                            if s[2:4] != b"\x00\x00":
                                # 说明不是 负载 帧尾部
                                l = struct.unpack("!H", s[2:4])
                                if l[0] +4 == len(s):
                                    # 还得判断是不是 这段数据是不是完整的 负载帧
                                    # 不焦虑，目前还没有到考虑数据校验、重发的情况，还是得相信串口总是好的
                                    # 如果是生产环境，必须要有 校验和重发 机制了
                                    socket_id = s[1]
                                    outS = s[4:].replace(b'\xff\xff', b'\xff')
                                    self.net_send_Queue.put((socket_id, outS))
                                elif i == len(sp_d) -2:
                                    # 如果是倒数第 2 帧，又不是完整的 负载帧
                                    # 就得 考虑 往 下一次 处理了
                                    comOutBuf = s
                            else:
                                pass
                except IndexError:
                    print ("Index Error ")
                    for s in sp_d[:-1]:
                        self.print_hex(s, " ")
                        print ("___e")

                if self.com_log != None:
                    for s in sp_d[:-1]:
                        self.com_log_file("R", s)
                # 处理最后一个子串
                s = sp_d[-1]
                if len(s) == 4:
                    if s[1] == 0xFE:
                        comOutBuf = b""
                        self.com_leading_packet_buf = s
                        self.com_leading_packet_proc()
                        if self.com_log != None:
                            self.com_log_file("R", s)
                    elif s[2:4] == b"\x00\x00":
                        #负载 帧尾部
                        comOutBuf = b""
                        if self.com_log != None:
                            self.com_log_file("R", s)
                    else:
                        #负载 帧头，不处理
                        comOutBuf += s
                else:
                    # 负载帧，不处理，放到下一次再来
                    comOutBuf += s
                """
                if self.debug >= 0:
                    print ("spd[-1] ",end=" ")
                    self.print_hex(comOutBuf, " ")
                    print ("")
                """
                """
                # 此处处理速度太慢，改写了加速版本
                # --------
                # --------
                # --------
                # --------
                while len(d) > 0:
                    # 很慢的版本
                    if leading_packet > 0:
                        leading_packet += 1
                        self.com_leading_packet_buf += d[0:1]
                        if leading_packet == 4:
                            if self.com_log != None:
                                self.com_log_file("R", self.com_leading_packet_buf)
                            leading_packet = 0
                            self.com_leading_packet_proc()
                    else:
                        if not look_FF:
                            if d[0] == 0xff:
                                look_FF = True
                            else:
                                comOutBuf += d[0:1]
                        else:
                            if d[0] == 0xff:
                                comOutBuf += b"\xff"
                                look_FF = False
                            else:
                                # d[0] != 0xff and FF_Count != 1
                                # 此种情况，说明遇见 帧头数据 了
                                look_FF = False
                                self.com_leading_packet_buf = b"\xff" + d[0:1]
                                #if self.debug:
                                #    print ("==", end=" ", flush=True)
                                leading_packet = 2
                                if len(comOutBuf) > 0:
                                    if self.com_log != None:
                                        self.com_log_file("R", comOutBuf)
                                    # 似乎有点问题，如果没有新的祯头，接收到的完整com数据负载就不外发？
                                    # ....已用数据负载帧的结束帧尾标记解决此问题
                                    self.net_send_Queue.put((self.com_sock_id_online, comOutBuf))
                                    comOutBuf = b""
                        eventlet.sleep(0)
                        # 这一段处理时间太长，需要hub让出一下
                    d = d[1:]
                """
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
    def Start(self, ConsoleMode=True):
        def run_circle(self):
            while True:
                try:
                    print ("Start Listening accept wait...")
                    new_sock, address = self.server_sock.accept()
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
        super().Start()
        print ("self.ip", self.ip)
        self.server_sock = eventlet.listen((self.ip, self.port), reuse_addr = True, backlog=0xfe)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        # 启动alive探测
        self.server_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 20)
        # 空闲时间    
        self.server_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 3)
        # 探测间隔
        self.server_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        # 探测次数
        # 这样对端连接断开后，最少 29秒后，本端也会断开
        self.pool.spawn_n(self.com_recv)
        self.pool.spawn_n(self.com_send)
        #pool.spawn_n(self.net_recv)
        # listen 的recv 只有被 accept 后，才会有
        self.pool.spawn_n(self.net_send)
        if ConsoleMode:
            run_circle(self)
        else:
            self.pool.spawn_n(run_circle, self)

    def Stop(self):
        super().Stop()
        try:
            self.server_sock.close()
        except Exception as e:
            print (e)
    def com_leading_packet_proc(self):
        if self.com_leading_packet_buf[1] == b"\xFE" \
        and self.com_leading_packet_buf[3] == 1:
            # 运行在客户模式下：
            # 01服务器返回连接失败的处理
            id = struct.unpack("!B", self.com_Forward_buf[1])
            sock = self.socket_stock[id]
            # 不管 close 是否 成功, 先必须把前导符号消除，因为 close 的动作会进入协程切换状态
            self.com_leading_packet_buf = b""
            sock.close()
            # 此处可以不回收 id，断开后，在net_recv中会有处理
            # self.socket_pool.put(id)
        else:
            super().com_leading_packet_proc()

class Socket2Ser_Server(Socket2Ser_Base):
    def Start(self, ConsoleMode=True):
        super().Start()
        #pool.spawn_n(self.com_recv)
        self.pool.spawn_n(self.com_send)        
        # pool.spawn_n(self.net_recv)
        # 只有从com发了连接信号后，才会去连接服务器，产生net_recv过程
        self.pool.spawn_n(self.net_send)
        self.pool.spawn_n(self.com_recv)
        # 启动读取 com 口的循环
        if ConsoleMode:
            while True:
                try:
                    eventlet.sleep(1)
                except (SystemExit, KeyboardInterrupt):
                    break
    def com_leading_packet_proc(self):
        #print ("buf:",self.com_leading_packet_buf)
        if self.com_leading_packet_buf[1] == 0xfe \
        and self.com_leading_packet_buf[3] == 0:
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
                # 启动网络 收报 协程
                self.pool.spawn_n(self.net_recv, sock, id)
            except:
                # 连接服务失败
                out_str = b"\xff\xfe" + struct.pack("!B", id) + b"\x01"
                self.com_send_Queue.put(out_str)
        else:
            super().com_leading_packet_proc()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Forward socket service to another computer via a serial port.")
    parser.add_argument('Action', choices=['S', 'C'], type=str, help='act as forwarding Server or Client')
    parser.add_argument('-ip', default='localhost', type=str, help="Connect to Server IP when act as Source, default is localhost")
    parser.add_argument('-port', default=22, type=int, nargs=1, required=True, help='Connect to Server port when act as source/Listen port when act as target, default is 22')
    parser.add_argument('-com', type=str, nargs=1, required=True, help="Serial Port")
    parser.add_argument('-baudrate', type=int, default=115200, help="Serial Port baudrate")
    parser.add_argument('-d', '--debug', choices=[0,1,2,3], type=int, default=0, help="set debug out")
    parser.add_argument('-b', "--backdoor", action="store_true", help="set backdoor debug")
    args = parser.parse_args()
    #print (args.port)

    if args.backdoor:
        eventlet.spawn(backdoor.backdoor_server, eventlet.listen(('localhost', 55555)), locals())
    if args.Action == "S":
        ss = Socket2Ser_Server(args.ip, args.port[0], args.com[0], args.baudrate, args.debug)
    else:
        ss = Socket2Ser_Client("localhost", args.port[0], args.com[0], args.baudrate, args.debug)
    ss.Start()
    ss.Stop()