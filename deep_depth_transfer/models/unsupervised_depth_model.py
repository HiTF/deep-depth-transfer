import pytorch_lightning as pl
import torch
import torch.nn as nn


class UnsupervisedDepthModel(pl.LightningModule):
    def __init__(self, pose_net, depth_net, criterion, optimizer_parameters, result_visualizer=None,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pose_net = pose_net
        self._depth_net = depth_net
        self._criterion = criterion
        self._result_visualizer = result_visualizer
        self._optimizer_parameters = optimizer_parameters
        self.example_input_array = (torch.zeros((1, 3, 128, 384), dtype=torch.float),
                                    torch.zeros((1, 3, 128, 384), dtype=torch.float))

    def init_weights(self):
        for module in self.modules():
            if isinstance(module, nn.Conv2d):
                torch.nn.init.xavier_uniform_(module.weight)
                if module.bias is not None:
                    module.bias.data.fill_(0.01)

    def depth(self, x):
        out = self._depth_net(x)
        return out

    def pose(self, x, reference_frame):
        (out_rotation, out_translation) = self._pose_net(x, reference_frame)
        return out_rotation, out_translation

    def forward(self, x, reference_frame):
        return self.depth(x), self.pose(x, reference_frame)

    def loss(self, batch):
        # current_left, next_left, current_right, next_right
        images = [
            batch["left_current_image"],
            batch["left_next_image"],
            batch["right_current_image"],
            batch["right_next_image"]
        ]
        depths = [self.depth(image) for image in images]
        transformations = [
            self.pose(images[0], images[1]),
            self.pose(images[1], images[0]),
            self.pose(images[2], images[3]),
            self.pose(images[3], images[2])
        ]
        return self._criterion(images, depths, transformations)

    def training_step(self, batch, *args):
        losses = self.loss(batch)
        result = pl.TrainResult(losses["loss"])
        result.log_dict(losses, on_step=True)
        return result

    def make_figure(self, batch, batch_index):
        if self._result_visualizer is None:
            return None
        if not self._result_visualizer.batch_index == batch_index:
            return None
        images = [
            batch["left_current_image"],
            batch["left_next_image"],
            batch["right_current_image"],
            batch["right_next_image"]
        ]
        depths = [self.depth(image[:1])[0] for image in images]
        images = [image[0] for image in images]
        return self._result_visualizer(images, depths)

    def validation_step(self, batch, batch_index: int):
        losses = self.loss(batch)

        figure = self.make_figure(batch, batch_index)
        if figure is not None:
            self.logger.log_figure("depth_reconstruction", figure, self.global_step)

        result = pl.EvalResult(checkpoint_on=losses["loss"])
        result.log_dict(losses, on_epoch=True)
        return result

    def configure_optimizers(self):
        return torch.optim.Adam(self.parameters(), **self._optimizer_parameters)
