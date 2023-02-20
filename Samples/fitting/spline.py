import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import splev, splrep

g_min_roughness  = 0.04472135955
g_max_smoothness = 1.0 - g_min_roughness

def smoothness_to_length(smoothness):
    if smoothness >= g_max_smoothness:
        return 1.0
    if smoothness <= 0.0:
        return 2.0/3.0
    
    roughness = 1.0 - smoothness
    alpha     = roughness * roughness
    alpha2    = alpha * alpha
    a         = np.sqrt(1.0 - alpha2)
    
    # [Source]
	# D. Chan: Material Advances in Call of Duty: WWII.
    return (a - alpha2 * np.arctanh(a)) / (a*a*a)
    
def fit():
    smoothness = np.linspace(0.0, g_max_smoothness, 10000)
    lengths    = np.vectorize(smoothness_to_length)(smoothness)
    indices    = lengths.argsort()
    smoothness = smoothness[indices]
    lengths    = lengths[indices]
    return splrep(lengths, smoothness, s=0.0001, k=3)

def check():
    tck = fit()
    t, c, k = tck
    # t: array of padded knot positions
    print(np.vectorize(float.hex)(t))
    # c: array of control points
    print(np.vectorize(float.hex)(c))
    # k: degree of the B-spline
    print(k)
    
    smoothness  = np.linspace(0.0, 1.0-0.045, 1000000)
    lengths     = np.vectorize(smoothness_to_length)(smoothness)
    rsmoothness = splev(lengths, tck)
    
    # Cheat for alpha = 0 and alpha = 1
    #rsmoothness[0]  = 0.0
    #rsmoothness[-1] = 1.0
    
    errors = rsmoothness - smoothness
    
    plt.figure()
    plt.plot(lengths, smoothness,  '+', color='black')
    plt.plot(lengths, rsmoothness, '+', color='blue')
    plt.figure()
    plt.plot(lengths, errors, '+', color='blue')
    
    index = np.argmax(np.abs(errors))
    print(smoothness[index], errors[index])
