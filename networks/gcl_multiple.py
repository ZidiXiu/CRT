"""
Generalized Contrastive Learning ICA
"""
import torch
import torch.nn as nn
import numpy as np

# Type hinting
from typing import Union, List, Optional, Any, Tuple
from torch import FloatTensor, LongTensor
from networks.MAF_flow_multiple import MAF


class ComponentwiseTransform(nn.Module):
    """A neural network module to represent trainable dimension-wise transformation."""
    def __init__(self, modules: Union[List[nn.Module], nn.ModuleList]):
        """
        Parameters:
            modules: list of neural networks each of which is a univariate function
                     (or additionally it can take an auxiliary input variable).
        """
        super().__init__()
        if isinstance(modules, list):
            self.module_list = nn.ModuleList(modules)
        else:
            self.module_list = modules

    def __call__(self, x: FloatTensor, aux: Optional[Any] = None):
        """Perform forward computation.
        Parameters:
            x: input tensor.
            aux: auxiliary variable.
        """
        if aux is not None:
            return torch.cat(tuple(self.module_list[d](x[:, (d, )], aux)
                                   for d in range(x.shape[1])),
                             dim=1)
        else:
            return torch.cat(tuple(self.module_list[d](x[:, (d, )])
                                   for d in range(x.shape[1])),
                             dim=1)


class ComponentWiseTransformWithAuxSelection(ComponentwiseTransform):
    """A special type of ``ComponentWiseTransform``
    that takes discrete auxiliary variables and
    uses it as labels to select the output value out of an output vector.
    """
    def __init__(self,
                 x_dim: int,
                 n_aux: int,
                 hidden_dim: int = 512,
                 n_layer: int = 1):
        """
        Parameters:
            x_dim: input variable dimensionality.
            n_aux: the cardinality of the label (auxiliary variable) candidates.
            hidden_dim: the number of the hidden units for each hidden layer (fixed across all hidden layers).
            n_layer: the number of layers to stack.
        """
        super().__init__([
            nn.Sequential(
                nn.Linear(1, hidden_dim), nn.ReLU(),
                *([nn.Linear(hidden_dim, hidden_dim),
                   nn.ReLU()] * n_layer), nn.Linear(hidden_dim, n_aux))
            for _ in range(x_dim)
        ])


    def __call__(self, x: FloatTensor, aux: FloatTensor):
        """Perform the forward computation.
        Parameters:
            x: input vector.
            aux: auxiliary variables.
        """
        outputs = torch.cat(tuple(self.module_list[d](x[:, (d, )]).unsqueeze(2)
                                  for d in range(x.shape[1])),
                            dim=2).sum(dim=2)
        result = outputs[torch.arange(len(outputs)), aux.flatten()]
        return result


class _LayerWithAux(nn.Module):
    """A utility wrapper class for a layer that passes the auxiliary variables."""
    def __init__(self, net: nn.Module):
        """
        Parameters:
            net: the neural network.
        """
        super().__init__()
        self.net = net

    def __call__(self, x: FloatTensor, aux: Optional[Any] = None):
        """Perform forward computation.
        Parameters:
            x: input tensor.
            aux: auxiliary variable.
        """
        return self.net(x), aux

class GeneralizedContrastiveICAModel(nn.Module):
    """Example implementation of the ICA (wrapper) model that can be trained via GCL.
    It takes a feature extractor to estimate the mixing function
    and adds a classification functionality to enable the training procedure of GCL.
    """
    def __init__(
            self,
#             network: nn.Module,
            dim: int,
            n_label: int,
            n_steps: int,
            hidden_size: int,
            n_hidden: int,
            major_num: int,
            componentwise_transform: Optional[ComponentwiseTransform] = None,
            linear: nn.Module = None,
            input_order: str = 'sequential'):
        """
        Parameters:
            network: An invertible neural network (of PyTorch).
            linear: A linear layer to be placed at the beginning of the classification layer.
            dim: The dimension of the input (i.e., the dimension of the signal source).
        """
        super().__init__()
        self.network = MAF(n_steps, dim, hidden_size, n_hidden, major_num, None, 'relu', \
            input_order, batch_norm=True)

        if componentwise_transform is not None:
            self.componentwise_transform = componentwise_transform
        else:
            self.componentwise_transform = ComponentWiseTransformWithAuxSelection(
                dim, n_label)

        if linear is not None:
            self.linear = _LayerWithAux(linear)
            self.classification_net = nn.Sequential(
                self.linear, self.componentwise_transform)
        else:
            self.linear = None
            self.classification_net = self.componentwise_transform

    def hidden(self, x: FloatTensor) -> FloatTensor:
        """Extract the hidden vector from the input data.
        Parameters:
            x: input tensor.
        """
        result, _ = self.network(x)
        return result

    def logpdf(self, x, major_label):
        """Extract the hidden vector from the input data.
        Parameters:
            x: input tensor.
            major_label: corresponding label in majority_label list
        """
        logpdf = self.network.log_prob(x, major_label)
        return logpdf



    def classify(self,
                 data: Tuple[FloatTensor, FloatTensor],
                 return_hidden: bool = True):
        """Perform classification using the model for GCL.
        Parameters:
            data: tuple of input vector (shape ``(n_sample, n_dim)) and the target labels (shape ``(n_sample, )``).
            return_hidden: whether to also return the hidden representation obtained by the model.
        """
        x, label = data
        hidden = self.hidden(x)

        output = self.classification_net(hidden, label)
        if return_hidden:
            return output, hidden
        else:
            return output


    def inv(self, x: FloatTensor) -> FloatTensor:
        """Perform inverse computation.
        Parameters:
            x: input data (FloatTensor).
        Returns:
            numpy array containing the input vectors.
        """
        result, _ = self.network.inverse(x)
        return result

    def forward(self, x: FloatTensor) -> FloatTensor:
        """Alias of ``hidden()``.
        Parameters:
            x: input data.
        """
        return self.hidden(x)

    def __call__(self, x: FloatTensor) -> FloatTensor:
        """Perform forward computation.
        Parameters:
            x: input data.
        """
        return self.forward(x)