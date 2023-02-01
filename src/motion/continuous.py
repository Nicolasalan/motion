#!/usr/bin/env python3

import rospy
import numpy as np
import math
import tf
import time

from geometry_msgs.msg import Twist, Pose
from sensor_msgs.msg import LaserScan
from nav_msgs.msg import Odometry
from gazebo_msgs.msg import ModelState
from gazebo_msgs.srv import SetLightProperties

from std_srvs.srv import Empty
from squaternion import Quaternion

from utils import Extension

class Env():
     def __init__(self, CONFIG_PATH):

          self.useful = Extension(CONFIG_PATH)
          rospy.init_node("gym", anonymous=True)

          # Function to load yaml configuration file
          param = self.useful.load_config("config.yaml")

          self.position = Pose()
          #self.goal_position = Pose()
          #self.goal_position.position.x = 0.
          #self.goal_position.position.y = 0.

          # set the initial state
          self.goal_model = param["goal_model"]
          self.goal_reached_dist = param["goal_reached_dist"]
          self.environment_dim = param["environment_dim"]
          self.time_delta = param["time_delta"]
          self.collision_dist = param["collision_dist"]
          self.robot = param["robot"]
          self.orientation_threshold = param["orientation_threshold"]
          self.cmd_linear = param["action_linear_max"]
          self.cmd_angular = param["action_angular_max"]
          self.noise_sigma = param["noise_sigma"]

          # initialize global variables
          self.odom_x = 0.0
          self.odom_y = 0.0
          self.goal_x = 0.0
          self.goal_y = 0.0

          self.prev_action = [0.0, 0.0]
          self.initial_distance = None

          self.scan_data = np.ones(self.environment_dim) * 10
          self.path_waypoints = param["waypoints"]
          self.goals = self.useful.path_goal(self.path_waypoints)
          #self.data = None
          self.last_odom = None
          #self.orientation = None

          # ROS publications and subscriptions
          self.pub_cmd_vel = rospy.Publisher(param["topic_cmd"], Twist, queue_size=10)
          self.odom = rospy.Subscriber(param["topic_odom"], Odometry, self.odom_callback, queue_size=10)
          self.scan = rospy.Subscriber(param["topic_scan"], LaserScan, self.scan_callback)

          # ROS services 
          self.reset = rospy.ServiceProxy('gazebo/reset_world', Empty)
          self.pause = rospy.ServiceProxy("/gazebo/pause_physics", Empty)
          self.unpause = rospy.ServiceProxy("/gazebo/unpause_physics", Empty)
          self.set_state = rospy.Publisher("gazebo/set_model_state", ModelState, queue_size=10)
          self.set_light_properties = rospy.ServiceProxy("/gazebo/set_light_properties", SetLightProperties)


          self.gaps = self.useful.array_gaps(self.environment_dim)
          rospy.sleep(1)

     def odom_callback(self, msg):
          """
          Processes an odometry message and updates the current pose of the robot.
          ======
          Params:
               odom_msg (Odometry): An odometry message containing the current pose of the robot.
               pose (Pose): The current pose of the robot, represented as a Pose object.
          """
          self.last_odom = msg.pose.pose

     def scan_callback(self, scan):
          """
          Sensor scan message that contains range data from a laser range finder
          ======
          Params:
               scan (LaserScan): list of range measurements, one for each beam in the scan.
               scan_data (array): A list of range measurements.
          """
          data = scan.ranges
          #noisy_data = data + np.random.normal(0, self.noise_sigma, data.shape)
          self.scan_data = self.useful.scan_rang(self.environment_dim, self.gaps, data)
          #self.data = self.useful.range(scan)

     def step_env(self, action):
          """
          Traverse the environment in a robot simulation
          ======
          Params:
               action (array): linear and angular speeds based on action values
               state (array): array with robot states (leisure, speed, distance and theta)
               reward (gloat): agent reward function
               done (bool): check if it collided with an object
               target (bool): check if you reached the target
          """

          rospy.logwarn('Step Environment             => Stepping environment ...')
          target = False

          # ================== PUBLISH ACTION ================== #
          try:
               # Publish the robot action
               vel_cmd = Twist()
               vel_cmd.linear.x = action[0] * self.cmd_linear
               vel_cmd.angular.z = action[1] * self.cmd_angular
               self.pub_cmd_vel.publish(vel_cmd)
               rospy.loginfo('Publish Action               => Linear: ' + str(vel_cmd.linear.x) + ' Angular: ' + str(vel_cmd.angular.z))

               vel_cmd.linear.x = self.prev_action[0]
               vel_cmd.angular.z = self.prev_action[1]

          except:
               rospy.logerr('Publish Action              => Failed to publish action')

          # ================== UNPAUSE SIMULATION ================== #
          rospy.wait_for_service("/gazebo/unpause_physics")
          try:
               self.unpause()

               time.sleep(self.time_delta)

               rospy.wait_for_service("/gazebo/pause_physics")

               self.pause()
               
               rospy.loginfo('Unpause Simulation           => Unpause simulation ...')
          except:
               rospy.logerr('Unpause Simulation          => Error unpause simulation')

          # ================== READ SCAN DATA ================== #
          
          done, collision, min_laser = self.useful.observe_collision(self.scan_data, self.collision_dist)

          try:
               v_state = []
               v_state[:] = self.scan_data[:]

               # add noise to the laser data
               noisy_state = np.clip(v_state + np.random.normal(0, self.noise_sigma, len(v_state)), 0, 10.0)
               state_laser = [list(noisy_state)]

               rospy.loginfo('Read Scan Data               => Min Lazer: ' + str(min_laser) + ' Collision: ' + str(collision) + ' Done: ' + str(done))
          
          except:
               rospy.logerr('Read Scan Data              => Error reading scan data')
               done = False
               collision = False
               min_laser = 0.0
               state_laser = [np.ones(self.environment_dim) * 10]

          # ================== READ ODOM DATA ================== #
          try:
               self.odom_x = self.last_odom.position.x
               self.odom_y = self.last_odom.position.y

               quaternion = (
                    self.last_odom.orientation.x,
                    self.last_odom.orientation.y,
                    self.last_odom.orientation.z,
                    self.last_odom.orientation.w
               )
               euler = tf.transformations.euler_from_quaternion(quaternion)
               yaw = euler[2]
               angle = math.degrees(yaw)
               rospy.loginfo('Read Odom Data               => Odom x: ' + str(self.odom_x) + ' Odom y: ' + str(self.odom_y) + ' Angle: ' + str(angle))

          except:
               rospy.logfatal('Read Odom Data              => Error reading odometry data')
               self.odom_x = 0.0
               self.odom_y = 0.0
               angle = 0.0
     
          # ================== CALCULATE DISTANCE AND THETA ================== #
          # Calculate distance to the goal from the robot
          distance = self.useful.distance_to_goal(self.odom_x, self.goal_x, self.odom_y, self.goal_y)
          # Calculate the relative angle between the robots heading and heading toward the goal
          theta = self.useful.angles(self.odom_x, self.goal_x, self.odom_y, self.goal_y, angle)

          rospy.loginfo('Calculate distance and angle => Distance: ' + str(distance) + ' Angle: ' + str(theta))

          # ================== ORIENTATION GOAL ================== #
          # Calculate difference between current orientation and target orientation
          orientation_diff = abs(angle - self.goal_orientation)

          rospy.loginfo('Orientation Goal             => Orientation Diff: ' + str(orientation_diff))

          # ================== CALCULATE DISTANCE AND ANGLE ================== #
          # Detect if the goal has been reached and give a large positive reward
          if distance < self.goal_reached_dist: #and orientation_diff < self.orientation_threshold:
               target = True
               done = True
          
          rospy.loginfo('Check (Collided or Arrive)   => Target: ' + str(target) + ' Done: ' + str(done))

          # ================== SET STATE ================== #
          robot_state = [distance, theta, action[0], action[1]]
          state = np.append(state_laser, robot_state)
          reward = self.useful.get_reward(target, collision, action, min_laser, distance, self.prev_action, self.initial_distance)

          self.initial_distance = distance

          rospy.loginfo('Get Reward                   => Reward: ' + str(reward))
          return state, reward, done, target

     def reset_env(self):
          """
          Resets the environment to a new position and sets the initial robot states
          ======
          Params:
               state (array): array with robot states (leisure, speed, distance and theta)
          """

          # ================== RESET ENVIRONMENT ================== #
          rospy.logwarn("Reset Environment            => Resetting environment ...")
          # Resets the state of the environment and returns an initial observation.
          rospy.wait_for_service("/gazebo/reset_simulation")
          try:
               self.reset()

          except:
               rospy.logerr('Reset Simulation           => Failed service call failed')

          # ================== SET RANDOM ANGLE ================== #
          angle = np.random.uniform(-np.pi, np.pi)
          quaternion = Quaternion.from_euler(0.0, 0.0, angle)
          rospy.loginfo('Set Random Angle Robot       => Angle: ' + str(angle))

          # ================== SET RANDOM ORIENTATION ================== #
          try:
               self.goal_orientation = np.random.uniform(-np.pi, np.pi)

               rospy.loginfo('Set Random Angle Target      => Angle: ' + str(self.goal_orientation))
          
          except:
               rospy.logerr('Set Random Orientation      => Error setting random orientation')
               self.goal_orientation = 0.0

          # ================== SET RANDOM POSITION ================== #
          
          path = self.goals
          x, y = 0.0, 0.0

          while True:
               x, y = self.useful.random_goal(path)
               _x, _y = self.useful.change_goal(path)
               check = self.useful.check_pose(x, y, _x, _y)
               if check == True:
                    break
                    
          rospy.loginfo('Set Random Position          => Goal: (' + str(x) + ', ' + str(y) + ') Robot: (' + str(self.odom_x) + ', ' + str(self.odom_y) + ')')

          # ================== SET RANDOM ROBOT MODEL ================== #
          try:
               set_robot = ModelState()
               set_robot.model_name = self.robot
               set_robot.pose.position.x = x
               set_robot.pose.position.y = y
               set_robot.pose.position.z = 0.0
               set_robot.pose.orientation.x = quaternion.x
               set_robot.pose.orientation.y = quaternion.y
               set_robot.pose.orientation.z = quaternion.z
               set_robot.pose.orientation.w = quaternion.w
               self.set_state.publish(set_robot)
          
          except:
               rospy.logerr('Set Random Robot Model       => Error setting random robot model')

          time.sleep(self.time_delta)

          # ================== SET RANDOM GOAL MODEL ================== #
          try:
               set_target = ModelState()
               set_target.model_name = "target"
               set_target.pose.position.x = _x
               set_target.pose.position.y = _y
               set_target.pose.position.z = 0.0
               set_target.pose.orientation.x = 0.0
               set_target.pose.orientation.y = 0.0
               set_target.pose.orientation.z = 0.0
               set_target.pose.orientation.w = 1.0
               self.set_state.publish(set_target)
               self.goal_x, self.goal_y = _x, _y
          
          except:
               rospy.logerr('Set Random Goal Model       => Error setting random goal model')

          # ================== UNPAUSE SIMULATION ================== #
          rospy.wait_for_service("/gazebo/unpause_physics")
          try:
               self.unpause()

               time.sleep(self.time_delta)

               rospy.wait_for_service("/gazebo/pause_physics")

               self.pause()
               
               rospy.loginfo('Unpause Simulation           => Unpause simulation ...')
          except:
               rospy.logerr('Unpause Simulation          => Error unpause simulation')

          # ================== GET STATE SCAN ================== #
          try:
               v_state = []
               v_state[:] = self.scan_data[:]
               laser_state = [v_state]

               rospy.loginfo('Get state scan               => Laser: ' + str(np.mean(laser_state)))
          except:
               rospy.logerr('Get state scan              => Error getting state scan')

          # ==================CALCULATE DISTANCE AND ANGLE ================== #
          # Calculate distance to the goal from the robot
          distance = self.useful.distance_to_goal(self.odom_x, self.goal_x, self.odom_y, self.goal_y)
          # Calculate the relative angle between the robots heading and heading toward the goal
          theta = self.useful.angles(self.odom_x, self.goal_x, self.odom_y, self.goal_y, angle)
          self.initial_distance = distance
          rospy.loginfo('Calculate distance and angle => Distance: ' + str(distance) + ' Angle: ' + str(theta))
          print('========================================================================================================================')
          self.useful.randomize_objects()

          # ================== CREATE STATE ARRAY ================== #
          robot_state = [distance, theta, 0.0, 0.0]
          state = np.append(laser_state, robot_state)

          # ================== RETURN STATE ================== #
          return np.array(state)