import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

img1 = np.array(Image.open('C:/Users/....png'), np.int32)
img2 = np.array(Image.open('C:/Users/....png'), np.int32)
img  = np.abs(img2 - img1)
img[:,:,3] = 255

plt.imshow(img)

Image.fromarray(np.array(img, np.uint8)).save('C:/Users/....png')
