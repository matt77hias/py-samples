import matplotlib.pyplot as plt
import numpy as np

###########################################################################
def normalize(v):
    norm = np.linalg.norm(v)
    if norm == 0:
       return v
    return v / norm

###############################################################################
def draw_polygon(axes, vertices, **kwargs):
    nb_vertices = len(vertices)
    if nb_vertices < 3:
        return
    
    for i in range(nb_vertices - 1):
        v1 = vertices[i]
        v2 = vertices[i + 1]
        axes.plot([v1[0], v2[0]], [v1[1], v2[1]], [v1[2], v2[2]], **kwargs)
        
    v1 = vertices[-1]
    v2 = vertices[0]  
    axes.plot([v1[0], v2[0]], [v1[1], v2[1]], [v1[2], v2[2]], **kwargs)
    
###############################################################################
def draw_reference(axes, T, R, S, **kwargs):
    
    def object_to_parent(v):
        return (S * v).dot(R) + T
        
    vs        = [None] * 8
    vs[0b000] = object_to_parent([-0.5, -0.5, -0.5])
    vs[0b001] = object_to_parent([-0.5, -0.5,  0.5])
    vs[0b010] = object_to_parent([-0.5,  0.5, -0.5])
    vs[0b011] = object_to_parent([-0.5,  0.5,  0.5])
    vs[0b100] = object_to_parent([ 0.5, -0.5, -0.5])
    vs[0b101] = object_to_parent([ 0.5, -0.5,  0.5])
    vs[0b110] = object_to_parent([ 0.5,  0.5, -0.5])
    vs[0b111] = object_to_parent([ 0.5,  0.5,  0.5])
    
    draw_polygon(axes, [vs[0b000], vs[0b001], vs[0b011], vs[0b010]], **kwargs)
    draw_polygon(axes, [vs[0b100], vs[0b101], vs[0b111], vs[0b110]], **kwargs)
    draw_polygon(axes, [vs[0b000], vs[0b001], vs[0b101], vs[0b100]], **kwargs)
    draw_polygon(axes, [vs[0b010], vs[0b011], vs[0b111], vs[0b110]], **kwargs)
    draw_polygon(axes, [vs[0b000], vs[0b010], vs[0b110], vs[0b100]], **kwargs)
    draw_polygon(axes, [vs[0b001], vs[0b011], vs[0b111], vs[0b101]], **kwargs)
   
###############################################################################
def test():
    figure = plt.figure()
    axes = figure.add_subplot(projection='3d')
    
    #vs = [np.array([-0.5, 0.0, -0.5]), np.array([-0.5, 0.0, 0.5]), np.array([0.5, 0.0, 0.5]), np.array([0.5, 0.0, -0.5])]
    #vs = [np.array([-0.5, 0.0, -0.5]), np.array([-0.5, 0.0, 1.0]), np.array([0.5, 0.0, 0.5]), np.array([0.5, 0.0, -0.5])]
    #vs = [np.array([-5.0, 0.0, -0.7]), np.array([-4.0, 0.0, 8.0]), np.array([4.0, 0.0, 5.0]), np.array([5.0, 0.0, 0.0])]
    vs = [np.random.rand(3), np.random.rand(3), np.random.rand(3), np.random.rand(3)]
    #vs = [np.random.rand(3), np.random.rand(3), np.random.rand(3)]
    draw_polygon(axes, vs, color='blue')
    
    T, R, S = convert(vs)
    draw_reference(axes, T, R, S, color='green')
    
###############################################################################
def convert(vs):   
    nb_vertices = len(vs)
    vertices = vs + [vs[0]]
    
    # Compute the centroid of the polygon.
    # Compute the 4 normalized edges of the polygon.
    # Determine the longest (unnormalized) edge of the polygon.
    centroid = np.zeros_like(vs[0])
    normalized_edges = [None] * nb_vertices
    max_edge_length = -np.inf;
    max_edge_length_index = 0
    for i in range(nb_vertices):
        centroid += vertices[i]
        edge = vertices[i+1] - vertices[i]
        edge_length = np.linalg.norm(edge)
        normalized_edges[i] = edge / edge_length
        if edge_length > max_edge_length:
            max_edge_length = edge_length
            max_edge_length_index = i
    centroid /= nb_vertices
    
    # Compute an orthonormal base for the OBB with the following constraints:
	 # * The first axis is aligned with the longest edge of the polygon;
	 # * The first and third axes align with the polygon if the polygon is planar;
	 # * No axes points away (i.e. negative y) from the sky in world space.
    def adjust_orientation(axis):
        return axis if axis[1] >= 0 else -axis
    def ortho(axis, reference):
        return axis - axis.dot(reference) * reference
    
    ax = normalized_edges[max_edge_length_index]
    ax = adjust_orientation(ax)
    az = ortho(normalized_edges[(max_edge_length_index + 1) % nb_vertices], ax)
    az = normalize(az)
    az = adjust_orientation(az)
    ay = np.cross(ax, az)
    ay = adjust_orientation(ay)
    
    # Compute the translation and rotation component.
    # translation         -> rotation         := scaled-local-to-world
    # inverse_translation -> inverse_rotation := world-to-scaled-local
    translation = centroid
    inverse_translation = -translation
    rotation = np.array([ax, ay, az])
    inverse_rotation = np.transpose(rotation)
    
    # Transform the polygon vertices to scaled local space to compute the extents of the OBB.
    smin =  np.inf * np.ones_like(vs[0])
    smax = -np.inf * np.ones_like(vs[0])
    for i in range(nb_vertices):
        v = (vs[i] + inverse_translation).dot(inverse_rotation)
        smin = np.minimum(smin, v)
        smax = np.maximum(smax, v)
    
    # Extrude the extents by the user provided offsets.
    smin -= np.array([0.0, 0.0, 0.0])
    smax += np.array([0.0, 0.0, 0.0])
    
    # Compute the centroid of the OBB in local space.
    centroid_local = 0.5 * (smax + smin)
	 # Compute the centroid of the OBB in world space.
    centroid_world = centroid_local.dot(rotation) + translation
    
    # Compute the updated translation component.
    translation = centroid_world
    inverse_translation = -translation
   
    # Transform the polygon vertices to local space to compute the radius of the OBB.
    radius = -np.inf * np.ones_like(vs[0])
    for i in range(nb_vertices):
        v = (vs[i] + inverse_translation).dot(inverse_rotation)
        radius = np.maximum(radius, np.abs(v))
    
    # Compute the updated scaling component.
    scale = 2.0 * radius;
    
    return translation, rotation, scale
