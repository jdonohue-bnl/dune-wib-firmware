#!/usr/bin/env python3

import os
import sys
import time
import pickle
import argparse
import numpy as np
import zmq
import json
from collections import deque
from matplotlib.figure import Figure
from matplotlib.colors import LogNorm

import wib_pb2 as wib

try:
    from matplotlib.backends.qt_compat import QtCore, QtWidgets, QtGui
except:
    from matplotlib.backends.backend_qt4agg import QtCore, QtWidgets, QtGui

if int(QtCore.qVersion().split('.')[0]) >= 5:
    from matplotlib.backends.backend_qt5agg import (
        FigureCanvas, NavigationToolbar2QT as NavigationToolbar)
else:
    from matplotlib.backends.backend_qt4agg import (
        FigureCanvas, NavigationToolbar2QT as NavigationToolbar)
        
class CustomNavToolbar(NavigationToolbar):
    NavigationToolbar.toolitems = (
        ('Home', 'Reset original view', 'home', 'home'),
        ('Back', 'Back to previous view', 'back', 'back'),
        ('Forward', 'Forward to next view', 'forward', 'forward'),
        (None, None, None, None),
        ('Pan', 'Pan axes with left mouse, zoom with right', 'move', 'pan'),
        ('Zoom', 'Zoom to rectangle', 'zoom_to_rect', 'zoom'),
        (None, None, None, None),
        ('Save', 'Save the figure', 'filesave', 'save_figure')
    )
    
    def __init__(self, *args, **kwargs):
        '''parent is expected to be a SignalView object'''
        super().__init__(*args, **kwargs)
        
class DataView(QtWidgets.QWidget):
    def __init__(self,parent=None,figure=None):
        super().__init__(parent=parent)
        if figure is None:
            figure = Figure(tight_layout=True)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.figure = figure
        self.fig_ax = self.figure.subplots()
        self.fig_canvas = FigureCanvas(self.figure)
        self.fig_canvas.draw()
        
        self.fig_toolbar = CustomNavToolbar(self.fig_canvas,self,coordinates=False)
        self.fig_toolbar.setParent(self.fig_canvas)
        self.fig_toolbar.setMinimumWidth(300)
        
        self.fig_canvas.mpl_connect("resize_event", self.resize)
        self.resize(None)
        
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(0,0,0,0)
        self.layout.setSpacing(0)
        self.layout.addWidget(self.fig_canvas)
        
        self.toolbar_shown(False)
        
        self.save_props = []
        
        self.last_lims = None
        
        self.times,self.data = None,None
    
    def resize(self, event):
        x,y = self.figure.axes[0].transAxes.transform((0,0.0))
        figw, figh = self.figure.get_size_inches()
        ynew = figh*self.figure.dpi-y - self.fig_toolbar.frameGeometry().height()
        self.fig_toolbar.move(int(x),int(ynew))
        
    def focusInEvent(self, *args, **kwargs):
        super().focusInEvent(*args, **kwargs)
        self.resize(None)
        self.toolbar_shown(True)
        
    def focusOutEvent(self, *args, **kwargs):
        super().focusOutEvent(*args, **kwargs)
        self.toolbar_shown(False)
    
    def toolbar_shown(self,shown):
        if shown:
            self.fig_toolbar.show()
        else:
            self.fig_toolbar.hide()
            
    def get_state(self):
        all_props = self.__dict__
        return {prop:getattr(self,prop) for prop in self.save_props if prop in all_props}
            
    def set_state(self, state):
        all_props = self.__dict__
        for prop,val in state.items():
            if prop in all_props:
                setattr(self,prop,val)
            
    def load_data(self,timestamps,samples):
        pass
        
    def plot_data(self,rescale=False):
        pass
        
class MeanRMSView(DataView):

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.twin_ax = self.fig_ax.twinx()
        self.chan = np.arange(128)
        self.rms = np.full_like(self.chan, 0)
        self.mean = np.full_like(self.chan, 0)
      
    def load_data(self,timestamps,samples):
        #timestamps = self.data_source.timestamps[0]
        samples = samples[0] # [femb][channel][sample] -> [channel][sample]
        self.rms = np.std(samples,axis=1)
        self.mean = np.mean(samples,axis=1)
        
        
    def plot_data(self,rescale=False):
        self.fig_ax.clear()
        self.twin_ax.clear()
        
        self.fig_ax.plot(self.chan,self.mean,drawstyle='steps',label='Mean',c='b')
        self.twin_ax.plot(self.chan,self.rms,drawstyle='steps',label='RMS',c='r')
        
        self.fig_ax.set_xlabel('Channel Number')
        self.fig_ax.set_ylabel('Mean ADC Counts')
        self.twin_ax.set_ylabel('RMS ADC Counts')
        
        self.fig_ax.legend(loc='upper left')
        self.twin_ax.legend(loc='upper right')
        self.fig_ax.figure.canvas.draw()
        self.resize(None)

class Hist2DView(DataView):

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.cb = None
        self.chan = np.arange(128)
        self.samples = np.arange(16385)
        x,_ = np.meshgrid(self.chan,self.samples)
        self.counts = np.zeros_like(x)
      
    def load_data(self,timestamps,samples):
        #timestamps = self.data_source.timestamps[0]
        samples = samples[0] # [femb][channel][sample] -> [channel][sample]
        self.counts = []
        for i in self.chan:
            counts,bins = np.histogram(samples[i],bins=self.samples)
            self.counts.append(counts)
        self.counts = np.asarray(self.counts)
        
    def plot_data(self,rescale=False):
        ax = self.fig_ax
        ax.clear()
        if self.cb is not None:
            self.cb.remove()
        
        try:
            im = ax.imshow(self.counts.T,extent=(self.chan[0],self.chan[-1],self.samples[0],self.samples[-1]),
                          aspect='auto',interpolation='none',origin='lower')
            self.cb = ax.figure.colorbar(im)
        except:
            pass
        
        ax.set_title('Sample Histogram')
        ax.set_xlabel('Channel Number')
        ax.set_ylabel('ADC Counts')
        
        ax.figure.canvas.draw()
        #self.resize(None)

class FFTView(DataView):

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.cb = None
        self.chan = np.arange(128)
        freq = np.fft.fftfreq(2184,320e-9) 
        freq_idx = np.argsort(freq)[len(freq)//2::]
        self.freq = freq[freq_idx]
        x,_ = np.meshgrid(self.chan,self.freq)
        self.fft = np.full_like(x,1)
        
    def load_data(self,timestamps,samples):
        #timestamps = self.data_source.timestamps[0]
        print(samples.shape)
        samples = samples[0] # [femb][channel][sample] -> [channel][sample]
        freq = np.fft.fftfreq(len(samples[0]),320e-9) 
        freq_idx = np.argsort(freq)[len(freq)//2::]
        self.freq = freq[freq_idx]
        self.fft = []
        for i in self.chan:
            fft = np.fft.fft(samples[i])
            self.fft.append(np.square(np.abs(fft[freq_idx])))
        self.fft = np.asarray(self.fft)
    
    def plot_data(self,rescale=False):
        ax = self.fig_ax
        ax.clear()
        if self.cb is not None:
            self.cb.remove()
        
        try:
            im = ax.imshow(self.fft.T,extent=(self.chan[0],self.chan[-1],self.freq[0]/1000,self.freq[-1]/1000),
                          aspect='auto',interpolation='none',origin='lower',norm=LogNorm())
            self.cb = ax.figure.colorbar(im)
        except:
            pass
        
        ax.set_title('Power Spectrum')
        ax.set_xlabel('Channel Number')
        ax.set_ylabel('Frequency (kHz)')
        
        ax.figure.canvas.draw()
        self.resize(None)
        
class FEMB0Diagnostics(QtWidgets.QMainWindow):
    def __init__(self,wib_server='127.0.0.1',config='femb0.json'):
        super().__init__()
        
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.connect('tcp://%s:1234'%wib_server)
        self.config = config
        
        self._main = QtWidgets.QWidget()
        self._main.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setCentralWidget(self._main)
        layout = QtWidgets.QVBoxLayout(self._main)
        
        self.grid = QtWidgets.QGridLayout()
        self.views = [Hist2DView(), MeanRMSView(), FFTView()]
        for i,v in enumerate(self.views):
            self.grid.addWidget(v,0,i)
        layout.addLayout(self.grid)
        
        nav_layout = QtWidgets.QHBoxLayout()
        
        button = QtWidgets.QPushButton('Configure')
        nav_layout.addWidget(button)
        button.setToolTip('Configure WIB and front end')
        button.clicked.connect(self.configure_wib)
        
        button = QtWidgets.QPushButton('Enable Pulser')
        nav_layout.addWidget(button)
        button.setToolTip('Toggle calibration pulser')
        button.clicked.connect(self.toggle_pulser)
        self.pulser_button = button
        
        button = QtWidgets.QPushButton('Acquire')
        nav_layout.addWidget(button)
        button.setToolTip('Read WIB Spy Buffer')
        button.clicked.connect(self.acquire_data)
        
        button = QtWidgets.QPushButton('Continuous')
        nav_layout.addWidget(button)
        button.setToolTip('Repeat acquisitions until stopped')
        button.clicked.connect(self.toggle_continuous)
        self.continuious_button = button
        
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.acquire_data)
        
        layout.addLayout(nav_layout)
        
        self.plot()
    
    def send_command(self,req,rep):
        cmd = wib.Command()
        cmd.cmd.Pack(req)
        self.socket.send(cmd.SerializeToString())
        rep.ParseFromString(self.socket.recv())
                
    @QtCore.pyqtSlot()
    def toggle_continuous(self):
        if self.continuious_button.text() == 'Continuous':
            self.continuious_button.setText('Stop')
            print('Starting continuous acquisition')
            self.timer.start(500)
        else:
            self.continuious_button.setText('Continuous')
            self.timer.stop()
    
    @QtCore.pyqtSlot()
    def acquire_data(self):
        print('Reading out WIB spy buffer')
        req = wib.ReadDaqSpy()
        req.buf0 = True
        req.buf1 = False
        req.deframe = True
        req.channels = True
        rep = wib.ReadDaqSpy.DeframedDaqSpy()
        self.send_command(req,rep)
        print('Successful:',rep.success)
        num = rep.num_samples
        print('Acquired %i samples'%num)
        self.samples = np.frombuffer(rep.deframed_samples,dtype=np.uint16).reshape((4,128,num))
        self.timestamps = np.frombuffer(rep.deframed_timestamps,dtype=np.uint64).reshape((2,num))
        
        for view in self.views:
            view.load_data(self.timestamps,self.samples)
            
        self.plot()
        
    @QtCore.pyqtSlot()
    def plot(self):
        for view in self.views:
            view.plot_data()
            
    @QtCore.pyqtSlot()
    def configure_wib(self):
        print('Loading config')
        try:
            with open(self.config,'rb') as fin:
                config = json.load(fin)
        except Exception as e:
            print('Failed to load config:',e)
            return
            
        print('Configuring FEMBs')
        req = wib.ConfigureWIB()
        req.cold = config['cold']
        for i in range(4):
            femb_conf = req.fembs.add();
            
            femb_conf.enabled = config['enabled_fembs'][i]
            
            fconfig = config['femb_configs'][i]
            
            #see wib.proto for meanings
            femb_conf.test_cap = fconfig['test_cap']
            femb_conf.gain = fconfig['gain']
            femb_conf.peak_time = fconfig['peak_time']
            femb_conf.baseline = fconfig['baseline']
            femb_conf.pulse_dac = fconfig['pulse_dac']

            femb_conf.leak = fconfig['leak']
            femb_conf.leak_10x = fconfig['leak_10x']
            femb_conf.ac_couple = fconfig['ac_couple']
            femb_conf.buffer = fconfig['buffer']

            femb_conf.strobe_skip = fconfig['strobe_skip']
            femb_conf.strobe_delay = fconfig['strobe_delay']
            femb_conf.strobe_length = fconfig['strobe_length']
        
        print('Sending ConfigureWIB command')
        rep = wib.Status()
        self.send_command(req,rep);
        print('Successful:',rep.success)
        
    @QtCore.pyqtSlot()
    def toggle_pulser(self):
        req = wib.Pulser()
        if self.pulser_button.text() == "Enable Pulser":
            req.start = True
            self.pulser_button.setText('Disable Pulser')
            print("Starting pulser")
        else:
            req.start = False
            self.pulser_button.setText('Enable Pulser')
            print("Stopping pulser")
        rep = wib.Status()
        self.send_command(req,rep);

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Visually display diagnostic data plots from FEMB0 on a WIB')
    parser.add_argument('--wib_server','-w',default='127.0.0.1',help='IP of wib_server to connect to [127.0.0.1]')
    parser.add_argument('--config','-C',default='femb0.json',help='WIB configuration to load [femb0.json]')
    args = parser.parse_args()
    
    
    qapp = QtWidgets.QApplication([])
    qapp.setApplicationName('FEMB0 Diagnostic Tool (%s)'%args.wib_server)
    app = FEMB0Diagnostics(**vars(args))
    app.show()
    qapp.exec_()
