# -*- coding: utf-8 -*-
import numpy as np
from plotter import Plotter2D, Plotter3D

# Cullable 26 - Group 348 - Capture A
f0 = np.array([np.array([2391.5, -8639.72, 8873.79]),
               np.array([604.466, -8640.33, 8860.79]),
               np.array([2383.8, -7835.2, 9002.94]),
               np.array([596.768, -7835.8, 8989.94]),
               np.array([0.086586, 6.40896, -5.83474]),
               np.array([0.0848846, 6.40895, -5.83475]),
               np.array([0.0865784, 6.40972, -5.83462]),
               np.array([0.084877, 6.40972, -5.83464])])

# Cullable 26 - Group 349 - Capture A
f1 = np.array([np.array([604.466, -8640.33, 8860.79]),
               np.array([-1182.57, -8640.94, 8847.79]),
               np.array([596.768, -7835.8, 8989.94]),
               np.array([-1190.27, -7836.41, 8976.94]),
               np.array([0.0848846, 6.40895, -5.83475]),
               np.array([0.0831833, 6.40895, -5.83477]),
               np.array([0.084877, 6.40972, -5.83464]),
               np.array([0.0831757, 6.40972, -5.83465])])

# Cullable 26 - Group 348 - Capture B
f2 = np.array([np.array([2401.94, -8636.92, 8874.31]),
               np.array([614.903, -8637.53, 8861.31]),
               np.array([2394.24, -7832.4, 9003.46]),
               np.array([607.206, -7833.01, 8990.46]),
               np.array([0.0865936, 6.40896, -5.83474]),
               np.array([0.0848923, 6.40896, -5.83475]),
               np.array([0.086586, 6.40973, -5.83462]),
               np.array([0.0848846, 6.40973, -5.83463])])

# Cullable 26 - Group 349 - Capture B
f3 = np.array([np.array([614.903, -8637.53, 8861.31]),
               np.array([-1172.13, -8638.14, 8848.31]),
               np.array([607.206, -7833.01, 8990.46]),
               np.array([-1179.83, -7833.62, 8977.46]),
               np.array([0.0848923, 6.40896, -5.83475]),
               np.array([0.0831909, 6.40896, -5.83477]),
               np.array([0.0848846, 6.40973, -5.83463]),
               np.array([0.0831833, 6.40972, -5.83465])])

def plot_frustum(f, indices, plotter, color):
    plotter.plot_line(f[0][indices], f[1][indices], color=color)
    plotter.plot_line(f[0][indices], f[2][indices], color=color)
    plotter.plot_line(f[0][indices], f[4][indices], color=color)
    plotter.plot_line(f[1][indices], f[3][indices], color=color)
    plotter.plot_line(f[1][indices], f[5][indices], color=color)
    plotter.plot_line(f[2][indices], f[3][indices], color=color)
    plotter.plot_line(f[2][indices], f[6][indices], color=color)
    plotter.plot_line(f[3][indices], f[7][indices], color=color)
    plotter.plot_line(f[4][indices], f[5][indices], color=color)
    plotter.plot_line(f[4][indices], f[6][indices], color=color)
    plotter.plot_line(f[5][indices], f[7][indices], color=color)
    plotter.plot_line(f[6][indices], f[7][indices], color=color)

capture_A = False
capture_B = True

def plot_xyz():
    plotter = Plotter3D()
    plotter.plot_AABB(np.array([-0.5, -0.5, -0.5]),
                      np.array([0.5, 0.5, 0.5]),
                      color='b')
    
    if capture_A:
        plot_frustum(f0, np.array([0, 1, 2]), plotter, color='r')
        plot_frustum(f1, np.array([0, 1, 2]), plotter, color='g')
    if capture_B:
        plot_frustum(f2, np.array([0, 1, 2]), plotter, color='r')
        plot_frustum(f3, np.array([0, 1, 2]), plotter, color='g')
    
    plotter.ax.set_xlim(-1.0, 1.0)
    plotter.ax.set_ylim(-1.0, 1.0)
    plotter.ax.set_zlim(-1.0, 1.0)
    

def plot_xy():
    plotter = Plotter2D()
    plotter.plot_AABB(np.array([-0.5, -0.5]),
                      np.array([0.5, 0.5]),
                      color='b')
    
    if capture_A:
        plot_frustum(f0, np.array([0, 1]), plotter, color='r')
        plot_frustum(f1, np.array([0, 1]), plotter, color='g')
    if capture_B:
        plot_frustum(f2, np.array([0, 1]), plotter, color='r')
        plot_frustum(f3, np.array([0, 1]), plotter, color='g')
    
    plotter.ax.set_xlim(-10.0, 10.0)
    plotter.ax.set_ylim(-10.0, 10.0)
    
def plot_xz():
    plotter = Plotter2D()
    plotter.plot_AABB(np.array([-0.5, -0.5]),
                      np.array([0.5, 0.5]),
                      color='b')
    
    if capture_A:
        plot_frustum(f0, np.array([0, 2]), plotter, color='r')
        plot_frustum(f1, np.array([0, 2]), plotter, color='g')
    if capture_B:
        plot_frustum(f2, np.array([0, 2]), plotter, color='r')
        plot_frustum(f3, np.array([0, 2]), plotter, color='g')
    
    plotter.ax.set_xlim(-10.0, 10.0)
    plotter.ax.set_ylim(-10.0, 10.0)
    
def plot_yz():
    plotter = Plotter2D()
    plotter.plot_AABB(np.array([-0.5, -0.5]),
                      np.array([0.5, 0.5]),
                      color='b')
    
    if capture_A:
        plot_frustum(f0, np.array([1, 2]), plotter, color='r')
        plot_frustum(f1, np.array([1, 2]), plotter, color='g')
    if capture_B:
        plot_frustum(f2, np.array([1, 2]), plotter, color='r')
        plot_frustum(f3, np.array([1, 2]), plotter, color='g')
    
    plotter.ax.set_xlim(-10.0, 10.0)
    plotter.ax.set_ylim(-10.0, 10.0)
 
plot_xyz()
plot_xy()
plot_xz()
plot_yz()
