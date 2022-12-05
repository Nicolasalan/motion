#!/usr/bin/env python3

import random
import torch
import numpy as np
import matplotlib.pyplot as plt

from collections import deque
from agent import Agent
from environment import Env

import rospy
import gym
import gym_gazebo
import numpy as np

state_dim = 16
action_dim = 2
action_linear_max = 0.25  # m/s
action_angular_max = 0.5  # rad/s

print('State Dimensions: ' + str(state_dim))
print('Action Dimensions: ' + str(action_dim))
print('Action Max: ' + str(action_linear_max) + ' m/s and ' + str(action_angular_max) + ' rad/s')

def ddpg(n_episodes=2000, print_every=10, max_t=1000, score_solved=30):
     rospy.init_node('ddpg_stage')
     env = Env()
     """
     Parâmetros
     ======
         n_episodes (int): número máximo de episódios de treinamento
         max_t (int): número máximo de timesteps por episódio
     """
     agent = Agent(state_size=state_dim, action_size=action_dim, random_seed=42)

     scores_window = deque()                                # pontuações médias dos episódios mais recentes
     scores = []                                            # lista de pontuações médias de cada episódio
                
     for i_episode in range(1, n_episodes+1):               # inicializar pontuação para cada agente
          agent.reset()                                     # redefinir ambiente
          states = env.reset()            # obtém o estado atual de cada agente
          var = 1.0

          for t in range(max_t):
               actions = agent.act(states)                   # selecione uma ação

               actions[0] = np.clip(np.random.normal(actions[0], var), 0., 1.)
               actions[1] = np.clip(np.random.normal(actions[1], var), -0.5, 0.5)

               state, reward, done, arrive = env.step(actions, past_action)
               env_info = env.step(actions)                  # e
               
               # salva a experiência no buffer de repetição, executa a etapa de aprendizado em um intervalo definido
               for state, action, reward, next_state, done in zip(states, actions, rewards, next_states, dones):
                    agent.step(state, action, reward, next_state, done, t)
                    
               states = next_states
               score += rewards
               if np.any(dones):                             # loop de saída quando o episódio termina
                    break              
               
          scores_window.append(score)                       # salvar pontuação média para o episódio
          scores.append(score)                              # salva pontuação média na janela
               
          print('\rEpisode {}\tAverage Score: {:.4f}'.format(i_episode, np.mean(scores_window)), end="") 
               
          if i_episode % print_every == 0:
               print('\rEpisode {}\tAverage Score: {:.4f}'.format(i_episode, np.mean(scores_window)))
          if np.mean(scores_window) >= score_solved:
               print('\nEnvironment solved in {:d} episodes!\tAverage Score: {:.4f}'.format(i_episode, np.mean(scores_window)))
               torch.save(agent.actor_local.state_dict(), 'actor_checkpoint.pth')
               torch.save(agent.critic_local.state_dict(), 'critic_checkpoint.pth')
               break

     return scores