import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

img1 = np.array(Image.open('C:/Users/....png'), np.uint32)
img2 = np.array(Image.open('C:/Users/....png'), np.uint32)
img  = (img1 + img2) / 2

plt.imshow(img)

Image.fromarray(np.array(img, np.uint8)).save('C:/Users/....png')
