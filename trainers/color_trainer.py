import time
import torch
import numpy as np

import models
import datasets
from models.networks import set_requires_grad
from models.reference_model import ReferenceModel
from .base_trainer import BaseTrainer
from evaluation import GroupEvaluator
from util.visualizer import Visualizer
from util.util import visualize_features, visualize_features_magnitude


class ColorTrainer(BaseTrainer):
    """
    Class for running the optimization of the model parameters.
    Implements transformation to the target feature/output,
    and trains the generator to match and perform such transformation.
    """
    @staticmethod
    def modify_commandline_options(parser, is_train):
        parser.add_argument("--lr", default=0.1, type=float)
        parser.add_argument("--beta1", default=0.9, type=float)
        parser.add_argument("--beta2", default=0.99, type=float)
        parser.add_argument("--lambda_l1_clr", default=8, type=float)
        parser.add_argument("--lambda_l1_bg", default=1, type=float)
        parser.add_argument("--lr_schedule", default='karras', choices=[None, 'karras'])
        parser.add_argument("--lr_rampup_length", default=0.05, type=float)
        parser.add_argument("--lr_rampdown_length", default=0.25, type=float)
        parser.add_argument("--max_iter", default=2000, type=int)
        parser.add_argument("--no_stylemix_aug", action='store_true')
        parser.add_argument("--stylemix_layers", default='8,16')
        parser.add_argument("--debug", action='store_true')

        parser.set_defaults(dataset_mode='color')
        return parser

    def __init__(self, opt):
        if opt.cudnn_benchmark:
            torch.backends.cudnn.benchmark = True

        self.model = models.create_model(opt)
        self.ref_model = ReferenceModel(opt)

        # update option
        opt.image_res = self.model.get_output_res()
        opt.target_res = self.model.get_target_res()
        self.opt = opt

        # some bookkeeping
        self.dataset = datasets.create_dataset(opt)
        self.visualizer = Visualizer(opt)
        if not opt.disable_eval:
            self.evaluators = GroupEvaluator(opt)

        # set up optimizers
        train_params = self.model.get_trainable_params()
        self.optimizer = torch.optim.Adam(train_params, lr=self.opt.lr, betas=(self.opt.beta1, self.opt.beta2))

        # set up losses
        self.set_loss_fn()

    def set_loss_fn(self):
        # main losses
        self.loss_l1 = torch.nn.L1Loss()

    def train_one_step(self, data_i, total_steps_so_far):
        # get model output at the target layer
        latents = data_i["latents"].to(self.model.device)

        # style-mixing augmentation
        if not self.opt.no_stylemix_aug:
            with torch.no_grad():
                z = torch.randn(self.opt.batch_size, self.model.netG.z_dim, device=self.model.device)
                w_mix = self.model.netG.mapping(z, None)
                m_start, m_end = [int(s) for s in self.opt.stylemix_layers.split(',')]
                latents[:, m_start:m_end, :] = w_mix[:, m_start:m_end, :]

        output = self.model(latents, mode='target')

        # get color supervision
        color_mask = data_i['color_masks'][:, None, :, :].to(output.device)
        masked_output = output * color_mask
        color_target = data_i['colors'].to(output.device)
        with torch.no_grad():
            color_target = color_target * color_mask

        # get background color constraint
        background_mask = data_i['background_masks'][:, None, :, :].to(output.device)
        background_output = output * background_mask
        with torch.no_grad():
            ref_output = self.ref_model(latents, mode='target')
            background_target = ref_output * background_mask

        # get the color losses
        losses = {}
        losses['L1_color'] = self.opt.lambda_l1_clr * self.loss_l1(masked_output, color_target)
        losses['L1_background'] = self.opt.lambda_l1_bg * self.loss_l1(background_output, background_target)

        # gather all losses and update parameters
        loss = sum([v.mean() for v in losses.values()])
        self.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        self.optimizer.step()

        return losses, output, None

    def visualize_training(self, step, data, output, target):
        with torch.no_grad():
            output_im = self.model(data['latents'], mode='output')
            ref_output = self.ref_model(data['latents'], mode='output')
            target_im = self.target_transform(ref_output, data).detach()

        vis = {}
        vis['output_im'] = output_im
        vis['target_im'] = target_im
        vis['output_feat'] = visualize_features(output)
        vis['target_feat'] = visualize_features(target)
        vis['output_featmagn'] = visualize_features_magnitude(output)
        vis['target_featmagn'] = visualize_features_magnitude(target)
        self.visualizer.display_current_results(step, vis)

    def fit(self):
        # start measuring training time
        torch.cuda.synchronize()
        start_time = time.time()

        # Set requires_grad to True only for trainable parameters for efficiency.
        set_requires_grad(self.ref_model.get_all_params(), False)
        set_requires_grad(self.model.get_all_params(), False)
        set_requires_grad(self.model.get_trainable_params(), True)

        for step in range(self.opt.max_iter):
            # load data, containing latent codes and data needed for transformation
            cur_data = next(self.dataset)

            # learning rate scheduling
            if self.opt.lr_schedule is not None:
                self.adjust_learning_rate(step)

            # train one step
            losses, output, target = self.train_one_step(cur_data, step)

            # logging
            self.visualizer.print_current_logs(step, {}, losses)
            self.visualizer.plot_current_logs(step, losses)

            # debug mode -- visualize training
            if self.opt.debug:
                self.visualize_training(step, cur_data, output, target)
                exit()

        # get total training time
        torch.cuda.synchronize()
        train_time = time.time() - start_time

        # save network
        self.save('final')

        # final evaluation and visualization (e.g., feature visualization, random samples)
        if not self.opt.disable_eval:
            models_to_eval = (self.ref_model, self.model)
            metrics, visuals = self.evaluators.evaluate(models_to_eval, self.dataset)
            metrics['runtime'] = train_time
            self.visualizer.plot_current_summaries(metrics)
            self.visualizer.display_current_results(step + 1, visuals, disable_html=True)

    def adjust_learning_rate(self, step):
        if self.opt.lr_schedule == 'karras':
            # Apply styleGAN Learning rate schedule.
            initial_learning_rate = self.opt.lr
            lr_rampup_length = self.opt.lr_rampup_length
            lr_rampdown_length = self.opt.lr_rampdown_length
            total_steps = self.opt.max_iter

            t = step / total_steps
            lr_ramp = min(1.0, (1.0 - t) / lr_rampdown_length)
            lr_ramp = 0.5 - 0.5 * np.cos(lr_ramp * np.pi)
            lr_ramp = lr_ramp * min(1.0, t / lr_rampup_length)
            lr = initial_learning_rate * lr_ramp
            for param_group in self.optimizer.param_groups:
                param_group['lr'] = lr
        else:
            raise KeyError(f"Unknown learning rate schedule: {self.opt.lr_schedule}")

    def get_visuals_for_snapshot(self, data_i):
        images = self.prepare_images(data_i)
        with torch.no_grad():
            return self.model(images, command="get_visuals_for_snapshot")

    def save(self, total_steps_so_far):
        self.model.save(total_steps_so_far)
