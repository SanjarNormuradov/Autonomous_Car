import gym
import numpy as np
import time
import os
import matplotlib.pyplot as plt
import torch
import argparse

from utils import BCPolicy, generate_paths, get_expert_data, RLPolicy, RLBaseline
from policy import MakeDeterministic
from bc import simulate_policy_bc
from dagger import simulate_policy_dagger
from policy_gradient import simulate_policy_pg
import pytorch_utils as ptu
from evaluate import evaluate

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print('using device', device)

torch.manual_seed(0)
import random
random.seed(0)
np.random.seed(0)


def plot_loss(losses:list, result_txt:list, policy_epoch=100, baseline_epoch=5, data_part=1.0, seed=0, output_directory=None, task='pg', num_traj=100):
    # Plot the loss
    fig, loss_plot = plt.subplots(figsize=(20, 10))
    fig.supxlabel(t='# epochs',
                  x=0.5, y=0.05, ha='center', va='baseline', fontsize='x-large')
    fig.supylabel(t='loss',
                  x=0.10, y=0.93, ha='left', va='top', fontsize='x-large')
    fig.suptitle(t=f'Loss reduction over {policy_epoch} epochs of training', 
                 x=0.5, y=0.90, ha='center', va='top', fontsize='x-large')
    fig.text(s=f"Success rate: {result_txt[0]}\nAverage reward (success only):  {result_txt[1]}\nAverage reward                 (all): {result_txt[2]}", 
             x=.65, y=.95, ha='left', va='top', fontsize='x-large')
    
    if task == 'behavior_cloning':
        filename = f"{output_directory}/epoch{policy_epoch}_part{data_part}_rs{seed}"
        loss_plot.plot(list(range(policy_epoch)), losses, linestyle='-', linewidth=2, marker='')
        fig.text(s=f"#Epochs = {policy_epoch}\nRandom Seed = {seed}\nPart of Expert Data = {data_part}",
                x=.16, y=.95, ha='left', va='top', fontsize='x-large')
        
    elif task == 'dagger':
        filename = f"{output_directory}/epoch{policy_epoch}_part{data_part}_rs{seed}"
        color_list = np.random.rand(2 * len(losses), 3)
        for i, loss in enumerate(losses):
            loss_plot.plot(list(range(policy_epoch)), loss, label=f"#DAgger iter: {i:2d}",
                           color=color_list[i], linestyle='-', linewidth=2, marker='')
        fig.text(s=f"#Epochs = {policy_epoch}\nRandom Seed = {seed}\nPart of Expert Data = {data_part}",
                x=.16, y=.95, ha='left', va='top', fontsize='x-large')
        fig.legend()

    elif task == 'pg':
        filename = f"{output_directory}/policy_epoch{policy_epoch}_baseline_epoch{baseline_epoch}_traj{num_traj}_rs{seed}"
        loss_plot.plot(list(range(policy_epoch)), losses, linestyle='-', linewidth=2, marker='')
        fig.text(s=f"#Policy Epochs = {policy_epoch}\n#Baseline Epochs = {baseline_epoch}\n#Trajectory rollouts = {num_traj}\nRandom Seed = {seed}",
                x=.16, y=.95, ha='left', va='top', fontsize='x-large')
        
    plt.savefig(filename + ".png", dpi=300, bbox_inches='tight')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', type=str, default='policy_gradient', help='choose task')
    parser.add_argument('--test', action='store_true', default=False)
    parser.add_argument('--render',  action='store_true', default=False)
    args = parser.parse_args()

    output_directory = f"plots_{args.task}"
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)
    stat_filename = f"{output_directory}/statistics1"

    if args.task == 'policy_gradient':
        # Define environment
        # 'InvertedPendulum' has action space of size 1 - (force on cart within [-3.0, 3.0], float32),
        #                        observation space of size 4 - ndarray[cartPos, vertAng_pole, linVel_cart, angulVel_pole]
        env = gym.make("InvertedPendulum-v2", render_mode="human") if args.render else gym.make("InvertedPendulum-v2")

        # Define policy and value function
        hidden_dim_pol = 64
        hidden_depth_pol = 2
        hidden_dim_baseline = 64
        hidden_depth_baseline = 2
        obs_size = env.observation_space.shape[0]
        ac_size = env.action_space.shape[0]

        # Training hyperparameters
        num_epochs = [200, ]
        max_path_length = 200
        pg_batch_size = [100, 50, ]
        gamma = 0.99
        baseline_train_batch_size = 64
        baseline_num_epochs = [5, 10, ]
        print_freq = 10
        num_validation_runs = 1000
        rand_seed = 1

        # Clear the content of stat_filename.txt before reuse
        with open(stat_filename + ".txt", "w") as file:
            pass

        for policy_epoch in num_epochs:
            with open(stat_filename + ".txt", "a") as file:
                file.write(f"""#policy_epoch = {policy_epoch}\n""")

            for baseline_num_epoch in baseline_num_epochs:
                with open(stat_filename + ".txt", "a") as file:
                    file.write(f"""#baseline_epoch = {baseline_num_epoch}\n""")

                for num_traj in pg_batch_size:
                    success = []
                    avg_reward_scc = []
                    avg_reward_all = []

                    for seed in range(rand_seed):
                        policy = RLPolicy(obs_size, ac_size, hidden_dim=hidden_dim_pol, hidden_depth=hidden_depth_pol).to(device)
                        baseline = RLBaseline(obs_size, hidden_dim=hidden_dim_baseline, hidden_depth=hidden_depth_baseline).to(device)
                        if not args.test:
                            print(f"\n#policy_epoch = {policy_epoch}\n#baseline_epoch = {baseline_num_epoch}\nnum_traj = {num_traj}\nrandom_seed = {seed}")
                            # Train policy gradient
                            losses = simulate_policy_pg(env, policy, baseline, num_epochs=policy_epoch, max_path_length=max_path_length, pg_batch_size=num_traj, gamma=gamma, 
                                                        baseline_train_batch_size=baseline_train_batch_size, baseline_num_epochs=baseline_num_epoch, print_freq=print_freq, 
                                                        render=args.render, seed=seed)
                            torch.save(policy.state_dict(), 'pg_final.pth')
                        else:
                            policy.load_state_dict(torch.load(f'pg_final.pth'))

                        result_txt = evaluate(env, policy, 'pg', num_validation_runs=num_validation_runs, episode_length=max_path_length, render=args.render)
                        success.append(float(result_txt[0]))
                        avg_reward_scc.append(float(result_txt[1]))
                        avg_reward_all.append(float(result_txt[2]))
                        plot_loss(losses=losses, result_txt=result_txt, policy_epoch=policy_epoch, baseline_epoch=baseline_num_epoch, 
                                  seed=seed, output_directory=output_directory, task='pg', num_traj=num_traj)

                        # Free up memory
                        del policy, baseline

                    with open(stat_filename + ".txt", "a") as file:
                        file.write(f"""num_traj = {num_traj}
                                success_rate:            mean = {np.mean(success):8.4f}; std = {np.std(success):8.4f}
                                average_reward(success): mean = {np.mean(avg_reward_scc):8.4f}; std = {np.std(avg_reward_scc):8.4f}
                                average_reward    (all): mean = {np.mean(avg_reward_all):8.4f}; std = {np.std(avg_reward_all):8.4f}\n\n""")

    if args.task == 'behavior_cloning':
        # Define environment
        # 'Reacher' has action space of size 2 - (torques for 2 hinge joints within [-1.0, 1.0], float32),
        #               observation space of size 11 - ndarray[cosJ1, cosJ2, sinJ1, sinJ2, targetX, targetY, angulVel_L1 angulVel_L2, 
        #                                                      x_diff(fingerTip - target), y_diff(fingerTip - target), 0]
        env = gym.make("Reacher-v2", render_mode="human") if args.render else gym.make("Reacher-v2")

        # Define policy
        hidden_dim = 128
        hidden_depth = 2
        obs_size = env.observation_space.shape[0]
        ac_size = env.action_space.shape[0]

        # Get the expert data
        file_path = 'data/expert_data.pkl'
        expert_data = get_expert_data(file_path)

        # Training hyperparameters
        episode_length = 50
        num_epochs = [500, 1000, 2000, ]
        batch_size = 32
        num_validation_runs = 10000
        expert_data_parts = [1.0, 0.5, 0.25, ]
        rand_seed = 5

        # Clear the content of stat_filename.txt before reuse
        with open(stat_filename + ".txt", "w") as file:
            pass
        
        for policy_epoch in num_epochs:
            with open(stat_filename + ".txt", "a") as file:
                file.write(f"""#epoch = {policy_epoch}\n""")

            for data_part in expert_data_parts:
                success = []
                avg_reward_scc = []
                avg_reward_all = []

                for seed in range(rand_seed):
                    # Reset policy for each different hyperparameter
                    policy = BCPolicy(obs_size, ac_size, hidden_dim=hidden_dim, hidden_depth=hidden_depth).to(device) # 10 dimensional latent
                    if not args.test:
                        print(f"\n#epoch = {policy_epoch}\nexpert_data_part = {data_part}\nrandom_seed = {seed}")
                        # Train behavior cloning
                        losses = simulate_policy_bc(env, policy, expert_data, num_epochs=policy_epoch, episode_length=episode_length,
                                        batch_size=batch_size, data_part=data_part, seed=seed)
                        torch.save(policy.state_dict(), 'bc_final.pth')
                    else:
                        policy.load_state_dict(torch.load(f'bc_final.pth'))

                    result_txt = evaluate(env, policy, 'bc', num_validation_runs=num_validation_runs, episode_length=episode_length, render=args.render)
                    success.append(float(result_txt[0]))
                    avg_reward_scc.append(float(result_txt[1]))
                    avg_reward_all.append(float(result_txt[2]))
                    plot_loss(losses=losses, result_txt=result_txt, policy_epoch=policy_epoch, data_part=data_part, 
                              seed=seed, output_directory=output_directory, task='behavior_cloning')

                    # Free up memory
                    del policy

                with open(stat_filename + ".txt", "a") as file:
                    file.write(f"""data_part = {data_part}
                               success_rate:            mean = {np.mean(success):8.4f}; std = {np.std(success):8.4f}
                               average_reward(success): mean = {np.mean(avg_reward_scc):8.4f}; std = {np.std(avg_reward_scc):8.4f}
                               average_reward    (all): mean = {np.mean(avg_reward_all):8.4f}; std = {np.std(avg_reward_all):8.4f}\n\n""")

    if args.task == 'dagger':
        # Define environment
        env = gym.make("Reacher-v2", render_mode="human") if args.render else gym.make("Reacher-v2")

        # Policy
        hidden_dim = 1000
        hidden_depth = 3
        obs_size = env.observation_space.shape[0]
        ac_size = env.action_space.shape[0]

        # Get the expert data
        file_path = 'data/expert_data.pkl'
        expert_data = get_expert_data(file_path)

        # Load interactive expert
        expert_policy = torch.load('data/expert_policy.pkl', map_location=torch.device(device)).to(device)
        print("Expert Policy loaded")
        # print(f"expert_policy:\n{expert_policy}")
        ptu.set_gpu_mode(True, gpu_id=0)

        # Training hyperparameters
        episode_length = 50
        num_epochs = [800, ]
        expert_data_parts = [1.0, ]
        batch_size = 32
        num_dagger_iters = 10
        num_trajs_per_dagger = 10
        num_validation_runs = 10000
        rand_seed = 2

        # Clear the content of stat_filename.txt before reuse
        with open(stat_filename + ".txt", "w") as file:
            pass
        
        for policy_epoch in num_epochs:
            with open(stat_filename + ".txt", "a") as file:
                file.write(f"""#epoch = {policy_epoch}\n""")

            for data_part in expert_data_parts:
                success = []
                avg_reward_scc = []
                avg_reward_all = []

                for seed in range(rand_seed):
                    # Reset policy for each different hyperparameter
                    policy = BCPolicy(obs_size, ac_size, hidden_dim=hidden_dim, hidden_depth=hidden_depth).to(device) # 10 dimensional latent
                    if not args.test:
                        print(f"\n#epoch = {policy_epoch}\nexpert_data_part = {data_part}\nrandom_seed = {seed}")
                        # Train DAgger
                        loss_list = simulate_policy_dagger(env, policy, expert_data, expert_policy, num_epochs=policy_epoch, episode_length=episode_length,
                                            batch_size=batch_size, num_dagger_iters=num_dagger_iters, num_trajs_per_dagger=num_trajs_per_dagger, 
                                            data_part=data_part, seed=seed)
                        torch.save(policy.state_dict(), 'dagger_final.pth')
                    else:
                        policy.load_state_dict(torch.load(f'dagger_final.pth'))

                    result_txt = evaluate(env, policy, 'dagger', num_validation_runs=num_validation_runs, episode_length=episode_length, render=args.render)
                    success.append(float(result_txt[0]))
                    avg_reward_scc.append(float(result_txt[1]))
                    avg_reward_all.append(float(result_txt[2]))
                    plot_loss(losses=loss_list, result_txt=result_txt, policy_epoch=policy_epoch, data_part=data_part, 
                              seed=seed, output_directory=output_directory, task='dagger')

                    # Free up memory
                    del policy

                with open(stat_filename + ".txt", "a") as file:
                    file.write(f"""data_part = {data_part}
                               success_rate:            mean = {np.mean(success):10.6f}; std = {np.std(success):10.6f}
                               average_reward(success): mean = {np.mean(avg_reward_scc):10.6f}; std = {np.std(avg_reward_scc):10.6f}
                               average_reward    (all): mean = {np.mean(avg_reward_all):10.6f}; std = {np.std(avg_reward_all):10.6f}\n\n""")
                    