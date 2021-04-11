# Script for modifying the world-to-object transformation matrix of an Oriented
# Bounding Box (OBB) to support expanding the OBB along its three canonical and
# inversed canonical axes.

import numpy as np

def scaling(s):
    return np.array([[s[0],  0.0,  0.0, 0.0],
                     [ 0.0, s[1],  0.0, 0.0],
                     [ 0.0,  0.0, s[2], 0.0],
                     [ 0.0,  0.0,  0.0, 1.0]])

def inverse_scaling(s):
    return scaling(1.0 / s)

def translation(t):
    return np.array([[ 1.0,  0.0,  0.0, 0.0],
                     [ 0.0,  1.0,  0.0, 0.0],
                     [ 0.0,  0.0,  1.0, 0.0],
                     [t[0], t[1], t[2], 1.0]])

def inverse_translation(t):
    return translation(-t)

def object_to_world(s, t):
    return np.dot(scaling(s), translation(t))
    
def world_to_object(s, t):
    return np.dot(inverse_translation(t), inverse_scaling(s))

def world_aabb(object_to_world):
    object_corners = [
        np.array([-0.5, -0.5, -0.5, 1.0]),
        np.array([-0.5, -0.5,  0.5, 1.0]),
        np.array([-0.5,  0.5, -0.5, 1.0]),
        np.array([-0.5,  0.5,  0.5, 1.0]),
        np.array([ 0.5, -0.5, -0.5, 1.0]),
        np.array([ 0.5, -0.5,  0.5, 1.0]),
        np.array([ 0.5,  0.5, -0.5, 1.0]),
        np.array([ 0.5,  0.5,  0.5, 1.0])
    ]
    world_min = np.array([+np.inf, +np.inf, +np.inf])
    world_max = np.array([-np.inf, -np.inf, -np.inf])
    for object_corner in object_corners:
        world_corner = np.dot(object_corner, object_to_world)
        world_min = np.minimum(world_min, world_corner[:3])
        world_max = np.maximum(world_max, world_corner[:3])
    return world_min, world_max

def object_aabb(world_to_object, world_min, world_max):
    world_corners = [
        np.array([world_min[0], world_min[1], world_min[2], 1.0]),
        np.array([world_min[0], world_min[1], world_max[2], 1.0]),
        np.array([world_min[0], world_max[1], world_min[2], 1.0]),
        np.array([world_min[0], world_max[1], world_max[2], 1.0]),
        np.array([world_max[0], world_min[1], world_min[2], 1.0]),
        np.array([world_max[0], world_min[1], world_max[2], 1.0]),
        np.array([world_max[0], world_max[1], world_min[2], 1.0]),
        np.array([world_max[0], world_max[1], world_max[2], 1.0])
    ]
    object_min = np.array([+np.inf, +np.inf, +np.inf])
    object_max = np.array([-np.inf, -np.inf, -np.inf])
    for world_corner in world_corners:
        object_corner = np.dot(world_corner, world_to_object)
        object_min = np.minimum(object_min, object_corner[:3])
        object_max = np.maximum(object_max, object_corner[:3])
    return object_min, object_max

def expand(world_min, world_max, world_min_delta, world_max_delta):
    world_center = (world_max + world_min)/2
    world_size   = (world_max - world_min)
    o2w = object_to_world(world_size, world_center)
    
    # object-to-world =  S R T
    # world-to-object = (S R T)^-1
    #
    #         T^-1              R^-1            S^-1
    #         T^-1              R^T             S^-1 
    # 
    # [   1   0   0  0 ] [  .  .  .  0 ] [ 1/sx    0    0 0]
    # [   0   1   0  0 ] [ R0 R1 R2  0 ] [    0 1/sy    0 0]
    # [   0   0   1  0 ] [  .  .  .  0 ] [    0    0 1/sz 0]
    # [ -tx -ty -tz  1 ] [  .  .  .  1 ] [    0    0    0 1]
    #
    #         T^-1              R^T S^-1   
    #
    # [   1   0   0  0 ] [   .     .     .    0 ]
    # [   0   1   0  0 ] [ R0/sx R1/sy R2/sz  0 ]
    # [   0   0   1  0 ] [   .     .     .    0 ]
    # [ -tx -ty -tz  1 ] [   .     .     .    1 ]
    #
    # [      .        .        .    0 ]
    # [    R0/sx    R1/sy    R2/sz  0 ]
    # [      .        .        .    0 ]
    # [ -t.R0/sx -t.R1/sy -t.R2/sz  1 ]
    
    # Extract the old scaling component
    sx = np.linalg.norm(o2w[0])
    sy = np.linalg.norm(o2w[1])
    sz = np.linalg.norm(o2w[2])
    s  = np.array([sx, sy, sz])
    # Expand the old scaling component
    new_s = s + (world_max_delta + world_min_delta)
    
    # Compute the R^T S^-1 columns
    c0 = o2w[0] / (s[0] * new_s[0])
    c1 = o2w[1] / (s[1] * new_s[1])
    c2 = o2w[2] / (s[2] * new_s[2])
    
    # Extract the old translation component
    t = o2w[3,:3]
    # Extract the old translation component
    new_t = t + (world_max_delta - world_min_delta) / 2
    
    # Compute the T^-1 R^T S^-1 columns
    c0[3] = np.dot(-new_t, c0[:3])
    c1[3] = np.dot(-new_t, c1[:3])
    c2[3] = np.dot(-new_t, c2[:3])
    
    # Construct the expanded world-to-object
    new_w2o = np.zeros((4,4))
    new_w2o[:,0] = c0
    new_w2o[:,1] = c1
    new_w2o[:,2] = c2
    new_w2o[3,3] = 1.0
    # Validate the expanded world-to-object
    print(object_aabb(new_w2o, new_t - new_s/2, new_t + new_s/2))
    
world_min = np.array([1.0, 2.0, 3.0])
world_max = np.array([5.0, 6.0, 7.0])
world_min_delta = np.array([1.0, 2.0, 3.0])
world_max_delta = np.array([5.0, 6.0, 7.0])
expand(world_min, world_max, world_min_delta, world_max_delta)
