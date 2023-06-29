# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function

# Powered by pygubu-designer
# pygubu-designer
# pip install pygubu-designer

from socket2ser import Socket2Ser_Client, Socket2Ser_Server
import serial.tools.list_ports as port_list
import eventlet, os
import socket

#!/usr/bin/python3
import tkinter as tk
import tkinter.ttk as ttk
from tkinter.scrolledtext import ScrolledText

def get_pc_ip_addresses():
    ip_addresses = ["localhost"]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        ip_addresses.append(s.getsockname()[0])
    except Exception:
        pass
    finally:
        s.close()
    return ip_addresses

class GuiS2SApp:
    def __init__(self, master=None):
        # build ui
        self.baseToplevel = tk.Tk() if master is None else tk.Toplevel(master)
        self.baseToplevel.configure(height=480, width=640)
        self.baseToplevel.resizable(False, False)
        self.baseToplevel.title("gui-socket2serial")
        self.cmbox_bdrate = ttk.Combobox(self.baseToplevel)
        self.cmbox_bdrate.configure(
            takefocus=False,
            values='9600 19200 38400 56000 115200 128000 460800 921600 1500000 2000000')
        self.cmbox_bdrate.grid(column=1, row=3)
        self.cmbox_COM = ttk.Combobox(self.baseToplevel)
        self.cmbox_COM.grid(column=0, row=3)
        self.btServer = ttk.Button(self.baseToplevel)
        self.btServer.configure(text='Run as Server')
        self.btServer.grid(column=0, row=0)
        self.btServer.bind("<ButtonPress>", self.runS_click, add="")
        self.txtSend = ScrolledText(self.baseToplevel)
        self.txtSend.configure(height=40, width=40)
        self.txtSend.grid(column=0, columnspan=2, row=5)
        self.txtRecv = ScrolledText(self.baseToplevel)
        self.txtRecv.configure(height=40, width=40)
        self.txtRecv.grid(column=2, columnspan=2, row=5)
        self.label1 = ttk.Label(self.baseToplevel)
        self.label1.configure(text='socket Send')
        self.label1.grid(column=0, columnspan=2, row=4)
        self.label2 = ttk.Label(self.baseToplevel)
        self.label2.configure(text='socket Recv')
        self.label2.grid(column=2, columnspan=2, row=4)
        self.label5 = ttk.Label(self.baseToplevel)
        self.label5.configure(text='COM')
        self.label5.grid(column=0, row=2)
        self.label6 = ttk.Label(self.baseToplevel)
        self.label6.configure(text='BaudRate')
        self.label6.grid(column=1, row=2)
        self.btClient = ttk.Button(self.baseToplevel)
        self.btClient.configure(text='Run as Client')
        self.btClient.grid(column=0, row=1)
        self.btClient.bind("<ButtonPress>", self.runC_click, add="")
        self.etPS = ttk.Entry(self.baseToplevel)
        self.intPortS = tk.IntVar(value=22)
        self.etPS.configure(textvariable=self.intPortS)
        _text_ = '22'
        self.etPS.delete("0", "end")
        self.etPS.insert("0", _text_)
        self.etPS.grid(column=3, row=0)
        self.etPC = ttk.Entry(self.baseToplevel)
        self.intPortC = tk.IntVar(value=12222)
        self.etPC.configure(textvariable=self.intPortC)
        _text_ = '12222'
        self.etPC.delete("0", "end")
        self.etPC.insert("0", _text_)
        self.etPC.grid(column=3, row=1)
        self.label7 = ttk.Label(self.baseToplevel)
        self.label7.configure(text='Port Forward')
        self.label7.grid(column=2, row=0)
        self.label8 = ttk.Label(self.baseToplevel)
        self.label8.configure(text='Port Listen')
        self.label8.grid(column=2, row=1)
        self.entry1 = ttk.Entry(self.baseToplevel)
        self.strIP_S = tk.StringVar(value='localhost')
        #self.entry1.configure(textvariable=self.strIP_S)
        #_text_ = 'localhost'
        self.entry1.delete("0", "end")
        self.entry1.insert("0", _text_)
        self.entry1.grid(column=1, row=0)
        self.cmbox_IP = ttk.Combobox(self.baseToplevel)
        self.cmbox_IP.grid(column=1, row=0)

        # Main widget
        self.mainwindow = self.baseToplevel

    def run(self):
        self.mainwindow.mainloop(n=5)

    def runS_click(self, event=None):
        print ("Run as Server")
        if self.btServer['text'] == "Run as Server":
            self.btServer['text'] = "Stop Server"
            self.btClient['state'] = "disable"
            self.txtRecv.delete("1.0","end")
            self.txtSend.delete("1.0","end")
            self.txtRecv_idx = 0
            self.txtSend_idx = 0
            COM_Name = self.com_ports[self.cmbox_COM.get()]
            print (COM_Name)
            log_file = "d:/stk/s2s_server.log"
            log_file = None
            self.ss = Socket2Ser_Server(ip=self.strIP_S.get(),\
                                        port=self.intPortS.get(), \
                                        com_port=COM_Name, \
                                        baud_rate=int(self.cmbox_bdrate.get()), \
                                        debug=0, \
                                        gui_debug=self.gui_debug,\
                                        com_log = log_file)
            self.ss.Start(ConsoleMode=False)
        else:
            self.btServer['text'] = "Run as Server"
            self.btClient['state'] = "normal"
            self.ss.Stop()

    def runC_click(self, event=None):
        print ("Run as Client")
        if self.btClient['text'] == "Run as Client":
            self.btClient['text'] = "Stop Client"
            self.btServer['state'] = "disable"
            self.txtRecv_idx = 0
            self.txtSend_idx = 0
            self.txtRecv.delete("1.0","end")
            self.txtSend.delete("1.0","end")
            COM_Name = self.com_ports[self.cmbox_COM.get()]
            print (COM_Name)
            log_file = "d:/stk/s2s_client.log"
            log_file = None
            self.ss = Socket2Ser_Client(ip="localhost",\
                                        port=self.intPortC.get(), \
                                        com_port=COM_Name, \
                                        baud_rate=int(self.cmbox_bdrate.get()), \
                                        debug=0, \
                                        gui_debug=self.gui_debug, \
                                        com_log = log_file)
            self.ss.Start(ConsoleMode=False)
        else:
            self.btClient['text'] = "Run as Client"
            self.btServer['state'] = "normal"
            self.ss.Stop()

    def gui_debug(self, SC, inStr):
        if SC == "r":
            self.txtRecv_idx +=1 
            #insert_pos = str(self.txtRecv_idx)+".0"
            #print (insert_pos, inStr)
            inStr = str(self.txtRecv_idx) + "\t" + inStr
            #self.txtRecv.insert(str(self.txtRecv_idx)+".0", inStr+"\n")
            self.txtRecv.insert(tk.END, inStr+"\n")
            self.txtRecv.update()
        else:
            self.txtSend_idx +=1
            inStr = str(self.txtRecv_idx) + "\t" + inStr
            #self.txtSend.insert(str(self.txtSend_idx)+".0", inStr+"\n")
            self.txtSend.insert(tk.END, inStr+"\n")
            self.txtSend.update()

    def on_closing(self):
        print ("on_closing")
        self.mainwindow.quit()        
        self.mainwindow.destroy()
        print ("self.mainwindow.destroy()")
        os._exit(0)

    def run_First(self):
        self.mainwindow.protocol("WM_DELETE_WINDOW", self.on_closing)
        ips = get_pc_ip_addresses()
        self.cmbox_IP["values"] = " ".join(ips)
        self.cmbox_IP.current(0)
        com_ports = list(port_list.comports())
        com_devices = [i.device for i in com_ports]
        com_description = [i.description for i in com_ports]
        self.com_ports = dict(zip(com_description, com_devices))
        self.cmbox_COM['value'] = com_description
        self.cmbox_COM.current(0)
        self.cmbox_bdrate.current(4)        
        self.txtRecv_idx = 0
        self.txtSend_idx = 0

    def coroutine_mainloop(self, n=0):
        while True:
            self.mainwindow.update_idletasks()
            self.mainwindow.update()
            eventlet.sleep(n)

if __name__ == "__main__":
    app = GuiS2SApp()
    app.run_First()
    #app.run()
    app.coroutine_mainloop()
