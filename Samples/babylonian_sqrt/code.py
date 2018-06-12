# Babylonian Method/Hero's Method 
def bsqrt(x, accuracy):
    x  = float(x)
    r0 = 0.5 * x
    e  = float('inf')
    print(r0,e)
    while e > accuracy:
        r1 = x / r0
        r2 = 0.5 * (r0 + r1)
        e  = abs(r1 - r2)
        r0 = r2
        print(r0,e)
