from lmfit import Model
import matplotlib.pyplot as plt
import numpy as np

def alpha_to_length(alpha):
    if alpha <= 0.0:
        return 1.0
    if alpha >= 1.0:
        return 2.0/3.0
   
    a = np.sqrt(1.0 - alpha*alpha)
    return (a - (1.0 - a*a) * np.arctanh(a)) / (a*a*a)

def non_linear_5PL(x, a, b, c, d, e):
    return d + (a-d) / np.power(1.0 + np.power(x/c, b), e)
def _non_linear_Inv5PL(x, a, b, c, d, e):
    return c * np.power(np.power((a-d)/(x-d), 1.0/e) - 1.0, 1.0/b)
def non_linear_Inv5PL(x, a, b, c, d, e):
    return c * np.power(np.power((a-d)/(x-d), e) - 1.0, b)   
    

def fit():
    alphas  = np.linspace(0.0, 1.0, 100000)
    lengths = np.vectorize(alpha_to_length)(alphas)
    indices = lengths.argsort()
    alphas  = alphas[indices]
    lengths = lengths[indices]
    
    model  = Model(non_linear_Inv5PL, nan_policy='propagate')
    params = model.make_params(a=1.0, b=1.0, c=1.0, d=-2.0, e=1.0)
    result = model.fit(alphas, x=lengths, params=params)
    
    print(result.fit_report())
    
    plt.plot(lengths, alphas, 'bo')
    plt.plot(lengths, result.init_fit, 'k--')
    plt.plot(lengths, result.best_fit, 'r-')
    plt.show()
