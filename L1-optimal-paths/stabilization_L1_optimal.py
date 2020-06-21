import numpy as np
import pulp as lpp
import cv2 as cv


# Read input video
cap = cv.VideoCapture('0.avi')

# Get frame count
n_frames = int(cap.get(cv.CAP_PROP_FRAME_COUNT))
print("Number of frames is {0}".format(n_frames))

# Get width and height of video stream
w = int(cap.get(cv.CAP_PROP_FRAME_WIDTH))
h = int(cap.get(cv.CAP_PROP_FRAME_HEIGHT))

# Define the codec for output video
fourcc = cv.VideoWriter_fourcc(*'MPEG')

# Get input fps, use same for output
fps = int(cap.get(cv.CAP_PROP_FPS))

# Set up output video stream
out = cv.VideoWriter('video_out.avi', fourcc, fps, (2*w, h))

# Read first frame
_, prev = cap.read()

# Convert frame to grayscale
prev_gray = cv.cvtColor(prev, cv.COLOR_BGR2GRAY)

# Pre-define transformation-store array
# Uses 3 parameters since it is purely a coordinate transform
transforms = np.zeros((n_frames - 1, 3), np.float32)

for i in range(n_frames - 2):
    # Detect feature points in previous frame
    prev_pts = cv.goodFeaturesToTrack(prev_gray, maxCorners=200, qualityLevel=0.01,
                                      minDistance=30, blockSize=3)

    # Read next frame
    success, curr = cap.read()
    if not success:
        break

    # Convert to grayscale
    curr_gray = cv.cvtColor(curr, cv.COLOR_BGR2GRAY)

    # Calculate optical flow (i.e. track feature points)
    curr_pts, status, err = cv.calcOpticalFlowPyrLK(prev_gray, curr_gray, prev_pts, None)

    # Sanity check
    assert prev_pts.shape == curr_pts.shape

    # Filter only valid points
    idx = np.where(status == 1)[0]
    prev_pts = prev_pts[idx]
    curr_pts = curr_pts[idx]

    # Find transformation matrix
    # This transform function is deprecated
    # use cv::estimateAffine2D, cv::estimateAffinePartial2D
    m, _ = cv.estimateAffine2D(prev_pts, curr_pts)  # will only work with OpenCV-3 or less

    # Extract translation
    dx = m[0, 2]
    dy = m[1, 2]

    # Extract rotation angle
    da = np.arctan2(m[1, 0], m[0, 0])

    # Store transformation
    transforms[i] = [dx, dy, da]

    # Move to next frame
    prev_gray = curr_gray

    # print("Frame: " + str(i) + "/" + str(n_frames) + " -  Tracked points : " + str(len(prev_pts)))

#print(transforms)

####
# Trajectory calculation, integrates changes to give current value of
# x, y, theta
#print(transforms.shape)
trajectory = np.cumsum(transforms, axis=0)
#print(trajectory.shape)
# print(trajectory)

# Apply linear programming to look for optimal stabilization + retargetting transform
# Initialise a PuLP Lp solver minimizer
    value_sum = LpProblem("MDP-Planning", LpMinimize)
    # Array to associate an index with every values(s) s \in S, variable
    values = np.arange(mdp.nstates)
    # Convert above indexing to dictionary form for pulp solver, vars named as Vs_i
    val_dict = LpVariable.dicts("Vs", values)
    # Add objective function (sum) to solver, pulp auto recognises this
    # to be the objective because it is added first
    value_sum += lpSum([val_dict[s] for s in values]), "Sum V(s), for all s in S"
    # Add primary constraints to solver in a nested loop
    for s in range(mdp.nstates):
        # One constraint for every action, from class notes
        for a in range(mdp.nactions):
            value_sum += val_dict[s] - lpSum([mdp.f_trans[s][a][s_prime] * (
                    mdp.f_reward[s][a][s_prime] + mdp.gamma * val_dict[s_prime]
            ) for s_prime in values]) >= 0, "Const: Vs_{0}, action-{1}".format(s, a)
    # If the MDP is episodic, find candidate terminal states
    # May be more than one but PA2 guarantees 1
    if mdp.type == "episodic":
        term_lst = mdp.get_terminal_states()
        # Add zero value function constraint when looking
        # ahead from a terminal state
        for term_state in term_lst:
            value_sum += val_dict[term_state] == 0, "Terminal State const. for state {0}".format(term_state)
    # Print formulation to a text file
    # value_sum.writeLP("formulation.lp")
    # Invoke pulp solver
    value_sum.solve()

    # If no solution found
    if value_sum.status != 1:
        print("error")
        exit(-1)
    # init optimal values vector
    values_opt = np.zeros(mdp.nstates)
    # Before reading out converged variable values to a vector, must ensure ordering
    # assign computed optimal values to vector
    for s in range(mdp.nstates):
        # Read in pulp variable name associated with current iteration
        cur_var = value_sum.variables()[s]
        # Assign to corresponding position in values_opt
        values_opt[int(cur_var.name.split('_')[1])] = cur_var.varValue
    # Get associated policy with V^*
    pi_opt = get_max_action_value(mdp, values_opt)
    return values_opt, pi_opt

# This needs to be replaced by the matrix multiplaication
# P_t = C_t B_t in the general case
def movingAverage(curve, radius):
    window_size = 2 * radius + 1
    # Define the filter
    f = np.ones(window_size)/window_size
    # Add padding to the boundaries
    curve_pad = np.lib.pad(curve, (radius, radius), 'edge')
    # Apply convolution
    curve_smoothed = np.convolve(curve_pad, f, mode='same')
    # Remove padding
    curve_smoothed = curve_smoothed[radius:-radius]
    # return smoothed curve
    return curve_smoothed


def smooth(trajectory):
    smoothed_trajectory = np.copy(trajectory)
    # Filter the x, y and angle curves
    for i in range(3):
        smoothed_trajectory[:,i] = movingAverage(trajectory[:, i], radius=3)

    return smoothed_trajectory


smoothed_trajectory = smooth(trajectory)

# Calculate difference in smoothed_trajectory and trajectory
difference = smoothed_trajectory - trajectory

# Calculate newer transformation array
transforms_smooth = transforms + difference


def fixBorder(frame):
    s = frame.shape
    # Scale the image 4% without moving the center
    T = cv.getRotationMatrix2D((s[1]/2, s[0]/2), 0, 1.04)
    frame = cv.warpAffine(frame, T, (s[1], s[0]))
    return frame


# Reset stream to first frame
cap.set(cv.CAP_PROP_POS_FRAMES, 0)

# Write n_frames-1 transformed frames
for i in range(n_frames - 2):
    # Read next frame
    success, frame = cap.read()
    if not success:
        break

    # Extract transformations from the new transformation array
    dx = transforms_smooth[i, 0]
    dy = transforms_smooth[i, 1]
    da = transforms_smooth[i, 2]

    # Reconstruct transformation matrix accordingly to new values
    m = np.zeros((2, 3), np.float32)
    m[0, 0] = np.cos(da)
    m[0, 1] = -np.sin(da)
    m[1, 0] = np.sin(da)
    m[1, 1] = np.cos(da)
    m[0, 2] = dx
    m[1, 2] = dy

    # Apply affine wrapping to the given frame
    frame_stabilized = cv.warpAffine(frame, m, (w, h))

    # Fix border artifacts
    frame_stabilized = fixBorder(frame_stabilized)

    # Write the frame to the file
    frame_out = cv.hconcat([frame, frame_stabilized])

    # If the image is too big, resize it.
    # if frame_out.shape[1] > 1920:

    frame_out = cv.resize(frame_out, (frame_out.shape[1], frame_out.shape[0]))

    cv.imshow("Before and After", frame_out)
    cv.waitKey(10)
    out.write(frame_out)

