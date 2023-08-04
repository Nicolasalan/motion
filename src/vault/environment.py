#!/usr/bin/env python3

import rospy
import numpy as np
import time
import math

from geometry_msgs.msg import Twist
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

          # set the initial state
          self.goal_reached_dist = param["GOAL_REACHED_DIST"]
          self.environment_dim = param["ENVIRONMENT_DIM"]
          self.time_delta = param["TIME_DELTA"]
          self.collision_dist = param["COLLISION_DIST"]
          self.robot = param["ROBOT"]
          self.orientation_threshold = param["ORIENTATION_THRESHOLD"]
          self.noise_sigma = param["NOISE_SIGMA"]
          self.cmd = param["TOPIC_CMD"]
          self.odom = param["TOPIC_ODOM"]
          self.scan = param["TOPIC_SCAN"]
          self.max_range = param["MAX_RANGE"]

          # initialize global variables
          self.odom_x = 0.0
          self.odom_y = 0.0
          self.goal_x = 1.0
          self.goal_y = 0.0

          self.last_odom_y = 0.0
          self.last_odom_x = 0.0

          self.path_waypoints = 'poses.yaml' # param["CONFIG_PATH"] + 'poses.yaml'
          self.path_random = 'random.yaml' # param["CONFIG_PATH"] + 'random.yaml'

          self.goals = self.useful.poses('poses.yaml')
          self.objects = self.useful.poses('random.yaml')
          self.last_odom = None
          self.distOld = 0

          # ROS publications and subscriptions
          self.pub_cmd_vel = rospy.Publisher(self.cmd, Twist, queue_size=10)
          self.odom = rospy.Subscriber(self.odom, Odometry, self.odom_callback, queue_size=10)
          self.scan = rospy.Subscriber(self.scan, LaserScan, self.scan_callback)

          # ROS services 
          self.reset = rospy.ServiceProxy('gazebo/reset_world', Empty)
          self.pause = rospy.ServiceProxy("/gazebo/pause_physics", Empty)
          self.unpause = rospy.ServiceProxy("/gazebo/unpause_physics", Empty)
          self.set_state = rospy.Publisher("gazebo/set_model_state", ModelState, queue_size=10)
          self.set_light_properties = rospy.ServiceProxy("/gazebo/set_light_properties", SetLightProperties)

          rospy.sleep(1)

     def odom_callback(self, msg):

          self.last_odom = msg.pose.pose

     def scan_callback(self, scan):

          scan_range = []
          for i in range(len(scan.ranges)):
               if scan.ranges[i] == float('Inf'):
                    scan_range.append(self.max_range)
               elif np.isnan(scan.ranges[i]):
                    scan_range.append(0)
               else:
                    scan_range.append(scan.ranges[i])
      
          self.scan_data = np.array(scan_range)

     def step_env(self, action):
          target = False

          # ================== PUBLISH ACTION ================== #
          try:
               vel_cmd = Twist()
               vel_cmd.linear.x = action[0]
               vel_cmd.angular.z = action[1]
               self.pub_cmd_vel.publish(vel_cmd)

          except:
               rospy.logerr('Publish Action              => Failed to publish action')

          # ================== UNPAUSE SIMULATION ================== #
          rospy.wait_for_service("/gazebo/unpause_physics")
          try:
               self.unpause()

               time.sleep(self.time_delta)

               rospy.wait_for_service("/gazebo/pause_physics")

               self.pause()
               
          except:
               rospy.logerr('Unpause Simulation          => Error unpause simulation')

          # ================== READ SCAN DATA ================== #

          min_laser = min(self.scan_data)
          if min_laser < self.collision_dist:
               done, collision, min_laser = True, True, min_laser
          else:
               done, collision, min_laser = False, False, min_laser

          try:
               v_state = []
               v_state[:] = self.scan_data[:]
               state_laser = [v_state]
          
          except:
               rospy.logfatal('Read Scan Data              => Error reading scan data')
               done = False
               collision = False
               min_laser = 0.0
               state_laser = [np.ones(self.environment_dim) * 10]

          # ================== READ ODOM DATA ================== #
          try:
               self.odom_x = self.last_odom.position.x
               self.odom_y = self.last_odom.position.y

               quaternion = Quaternion(
                    self.last_odom.orientation.x,
                    self.last_odom.orientation.y,
                    self.last_odom.orientation.z,
                    self.last_odom.orientation.w
               )
               euler = quaternion.to_euler(degrees=False)
               angle = round(euler[2], 4)
          except:
               rospy.logfatal('Read Odom Data              => Error reading odometry data')
               self.odom_x = 0.0
               self.odom_y = 0.0
               angle = 0.0

          # ================== CALCULATE DISTANCE AND THETA ================== #
          distance = np.linalg.norm([self.odom_x - self.goal_x, self.odom_y - self.goal_y])

          skew_x = self.goal_x - self.odom_x
          skew_y = self.goal_y - self.odom_y
          dot = skew_x * 1 + skew_y * 0
          mag1 = math.sqrt(math.pow(skew_x, 2) + math.pow(skew_y, 2))
          mag2 = math.sqrt(math.pow(1, 2) + math.pow(0, 2))
          if mag1 * mag2 == 0:
               beta = 0
          else:
               beta = math.acos(dot / (mag1 * mag2))
          if skew_y < 0:
               if skew_x < 0:
                    beta = -beta
               else:
                    beta = 0 - beta
          theta = beta - angle
          if theta > np.pi:
               theta = np.pi - theta
               theta = -np.pi - theta
          if theta < -np.pi:
               theta = -np.pi - theta
               theta = np.pi - theta

          # ================== ORIENTATION GOAL ================== #
          orientation_diff = abs(angle - self.goal_orientation)
          if self.odom_x == self.last_odom_x and self.odom_y == self.last_odom_y:
               done = True

          # ================== CALCULATE DISTANCE AND ANGLE ================== #
          if distance < self.goal_reached_dist: # and orientation_diff < self.orientation_threshold:
               target = True
               done = True
     
          # ================== SET STATE ================== #

          reward = 0.0
          robot_state = [distance, theta, action[0], action[1]]
          state = np.append(state_laser, robot_state)
          
          if target:
               reward =  100.0
          elif collision:
               reward = -100.0
          else:
               r3 = lambda x: 1 - x if x < 1 else 0.0
               reward = (action[0] / 2 - abs(action[1]) / 2 - r3(min_laser) / 2)

          self.last_odom_x, self.last_odom_y = self.odom_x, self.odom_y
          self.distOld = distance

          return state, reward, done, target

     def reset_env(self):

          rospy.wait_for_service("/gazebo/reset_simulation")
          try:
               self.reset()

          except:
               rospy.logerr('Reset Simulation           => Failed service call failed')

          # ================== SET RANDOM ANGLE ================== #
          angle = np.random.uniform(-np.pi, np.pi)
          quaternion = Quaternion.from_euler(0.0, 0.0, angle)

          # ================== SET RANDOM ORIENTATION ================== #
          try:
               self.goal_orientation = np.random.uniform(-np.pi, np.pi)
          
          except:
               rospy.logerr('Set Random Orientation      => Error setting random orientation')
               self.goal_orientation = 0.0

          # ================== SET RANDOM POSITION ================== #

          time.sleep(self.time_delta)

          goal, robot = self.select_poses(self.goals)

          # ================== SET RANDOM ROBOT MODEL ================== #
          try:
               set_robot = ModelState()
               set_robot.model_name = self.robot
               set_robot.pose.position.x = robot[0]
               set_robot.pose.position.y = robot[1]
               set_robot.pose.position.z = 0.0
               set_robot.pose.orientation.x = quaternion.x
               set_robot.pose.orientation.y = quaternion.y
               set_robot.pose.orientation.z = quaternion.z
               set_robot.pose.orientation.w = quaternion.w
               self.set_state.publish(set_robot)
               self.odom_x, self.odom_y = robot[0], robot[1]
          
          except:
               rospy.logerr('Set Random Robot Model       => Error setting random robot model')

          time.sleep(self.time_delta)

          # ================== SET RANDOM GOAL MODEL ================== #
          try:
               set_target = ModelState()
               set_target.model_name = 'target'
               set_target.pose.position.x = goal[0]
               set_target.pose.position.y = goal[1]
               set_target.pose.position.z = 0.0
               set_target.pose.orientation.x = 0.0
               set_target.pose.orientation.y = 0.0
               set_target.pose.orientation.z = 0.0
               set_target.pose.orientation.w = 1.0
               self.set_state.publish(set_target)
               self.goal_x, self.goal_y = goal[0], goal[1]
          
          except:
               rospy.logerr('Set Random Goal Model       => Error setting random goal model')
          
          time.sleep(self.time_delta)

          # ================== UNPAUSE SIMULATION ================== #
          rospy.wait_for_service("/gazebo/unpause_physics")
          try:
               self.unpause()

               time.sleep(self.time_delta)

               rospy.wait_for_service("/gazebo/pause_physics")

               self.pause()
               
          except:
               rospy.logerr('Unpause Simulation          => Error unpause simulation')

          # ================== GET STATE SCAN ================== #
          try:
               v_state = []
               v_state[:] = self.scan_data[:]

               state_laser = [v_state] 

          except:
               rospy.logerr('Get state scan              => Error getting state scan')
               state_laser = np.random.uniform(0, self.max_range, self.environment_dim)

          # ==================CALCULATE DISTANCE AND ANGLE ================== #
          distance = np.linalg.norm([self.odom_x - self.goal_x, self.odom_y - self.goal_y])

          skew_x = self.goal_x - self.odom_x
          skew_y = self.goal_y - self.odom_y
          dot = skew_x * 1 + skew_y * 0
          mag1 = math.sqrt(math.pow(skew_x, 2) + math.pow(skew_y, 2))
          mag2 = math.sqrt(math.pow(1, 2) + math.pow(0, 2))
          if mag1 * mag2 == 0:
               beta = 0
          else:
               beta = math.acos(dot / (mag1 * mag2))
          if skew_y < 0:
               if skew_x < 0:
                    beta = -beta
               else:
                    beta = 0 - beta
          theta = beta - angle
          if theta > np.pi:
               theta = np.pi - theta
               theta = -np.pi - theta
          if theta < -np.pi:
               theta = -np.pi - theta
               theta = np.pi - theta
               
          # ================== CREATE STATE ARRAY ================== #
          robot_state = [distance, theta, 0.0, 0.0]
          state = np.append(state_laser, robot_state)

          # ================== RETURN STATE ================== #
          return np.array(state)
     
     # ==== Random Functions ==== #
     def select_poses(self, poses):
          """Select two random poses from the list of poses."""

          if len(poses) < 2:
               raise ValueError("The 'poses' list must have at least two elements")

          index_robot = int(round(np.random.uniform(0, len(poses))))
          index_target = int(round(np.random.uniform(0, len(poses))))

          # Make sure that the robot and target are not the same
          while index_robot == index_target:
               index_target = int(round(np.random.uniform(0, len(poses))))

          # Make sure that the robot and target are not too close to each other
          while index_robot >= len(poses) or index_target >= len(poses):
               index_robot = int(round(np.random.uniform(0, len(poses))))
               index_target = int(round(np.random.uniform(0, len(poses))))

          return poses[index_robot], poses[index_target]