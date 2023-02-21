import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import shapiro

samples = np.array([38.0701981, 18.1168232, 17.9941730, 17.4855843, 16.7951088, 18.5931644, 15.3702908, 19.0282631, 16.8349705, 16.5393467, 17.4532681, 16.1172333, 17.7229652, 18.3390198, 41.0997581, 17.4979019, 25.3577003, 17.8133430, 81.1057663, 38.0733528, 37.7681732, 38.9454575, 41.4883347, 38.7622604, 39.5965919, 42.4001884, 39.6467743, 43.3832970, 37.6067886, 48.0079575, 17.7824974, 44.5712128])

mean = np.mean(samples)
var  = np.var(samples, ddof=1)
std  = np.std(samples, ddof=1)
iqr  = 0.67448 * std
smin = mean - iqr
smax = mean + iqr

plt.figure()

target = np.inf
for sample in samples:
    if sample <= smin:
        plt.scatter(sample, 0.0, color='blue')
    elif sample >= smax:
        plt.scatter(sample, 0.0, color='red')
    else:
        plt.scatter(sample, 0.0, color='green')
        target = min(target, sample)
    
plt.plot([smin,smin], [-1.0,1.0], color='blue')
plt.plot([mean-std,mean-std], [-1.0,1.0], color='black')
plt.plot([mean,mean], [-1.0,1.0], color='black')
plt.plot([mean+std,mean+std], [-1.0,1.0], color='black')
plt.plot([smax,smax], [-1.0,1.0], color='red')

plt.hist(samples, bins=11, histtype='step', color='black')

stat, p = shapiro(samples)
print('Statistics = %.3f, p-value = %.3f' % (stat, p))
alpha = 0.05
if p > alpha:
	print('Fail to reject H0: normal distribution')
else:
	print('Reject H0: no normal distribution')
    
print(target)
