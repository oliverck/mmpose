# Copyright (c) OpenMMLab. All rights reserved.
import warnings
from typing import Dict, Optional, Sequence, Union

import numpy as np
from mmengine.evaluator import BaseMetric
from mmengine.logging import MMLogger

from mmpose.registry import METRICS
from ..functional import (keypoint_auc, keypoint_epe, keypoint_nme,
                          keypoint_pck_accuracy)


@METRICS.register_module()
class PCKAccuracy(BaseMetric):
    """PCK accuracy evaluation metric.

    Calculate the pose accuracy of Percentage of Correct Keypoints (PCK) for
    each individual keypoint and the averaged accuracy across all keypoints.
    PCK metric measures accuracy of the localization of the body joints.
    The distances between predicted positions and the ground-truth ones
    are typically normalized by the person bounding box size.
    The threshold (thr) of the normalized distance is commonly set
    as 0.05, 0.1 or 0.2 etc.

    Note:
        - length of dataset: N
        - num_keypoints: K
        - number of keypoint dimensions: D (typically D = 2)

    Args:
        thr(float): Threshold of PCK calculation. Default: 0.05.
        norm_item (str | Sequence[str]): The item used for normalization.
            Valid items include 'bbox', 'head', 'torso', which correspond
            to 'PCK', 'PCKh' and 'tPCK' respectively. Default: ``'bbox'``.
        collect_device (str): Device name used for collecting results from
            different ranks during distributed training. Must be ``'cpu'`` or
            ``'gpu'``. Default: ``'cpu'``.
        prefix (str, optional): The prefix that will be added in the metric
            names to disambiguate homonymous metrics of different evaluators.
            If prefix is not provided in the argument, ``self.default_prefix``
            will be used instead. Default: ``None``.
    """
    default_prefix: Optional[str] = 'pck'

    def __init__(self,
                 thr: float = 0.05,
                 norm_item: Union[str, Sequence[str]] = 'bbox',
                 collect_device: str = 'cpu',
                 prefix: Optional[str] = None) -> None:
        super().__init__(collect_device=collect_device, prefix=prefix)
        self.thr = thr
        self.norm_item = norm_item if isinstance(norm_item,
                                                 (tuple,
                                                  list)) else [norm_item]
        allow_normalized_items = ['bbox', 'head', 'torso']
        for item in self.norm_item:
            if item not in allow_normalized_items:
                raise KeyError(
                    f'The normalized item {item} is not supported by '
                    f"{self.__class__.__name__}. Should be one of 'bbox', "
                    f"'head', 'torso', but got {item}.")

    def process(self, data_batch: Sequence[dict],
                predictions: Sequence[dict]) -> None:
        """Process one batch of data samples and predictions. The processed
        results should be stored in ``self.results``, which will be used to
        compute the metrics when all batches have been processed.

        Args:
            data_batch (Sequence[dict]): A batch of data
                from the dataloader.
            predictions (Sequence[dict]): A batch of outputs from
                the model.
        """
        for data, pred in zip(data_batch, predictions):
            # predicted keypoints coordinates, [1, K, D]
            pred_coords = pred['pred_instances']['keypoints'].cpu().numpy()
            # ground truth data_info
            gt = data['data_sample']['gt_instances']
            # ground truth keypoints coordinates, [1, K, D]
            gt_coords = gt['keypoints']
            # ground truth keypoints_visible, [1, K, 1]
            mask = gt['keypoints_visible'].reshape(1, -1)

            result = {
                'pred_coords': pred_coords,
                'gt_coords': gt_coords,
                'mask': mask,
            }

            if 'bbox' in self.norm_item:
                assert 'bboxes' in gt, 'The ground truth data info do not ' \
                    'have the expected normalized_item ``"bbox"``.'
                # ground truth bboxes, [1, 4]
                bbox_size_ = np.max(gt['bboxes'][0][2:])
                bbox_size = np.array([bbox_size_, bbox_size_]).reshape(-1, 2)
                result['bbox_size'] = bbox_size

            if 'head' in self.norm_item:
                assert 'head_size' in gt, 'The ground truth data info do ' \
                    'not have the expected normalized_item ``"head_size"``.'
                # ground truth bboxes
                head_size_ = gt['head_size']
                head_size = np.array([head_size_, head_size_]).reshape(-1, 2)
                result['head_size'] = head_size

            if 'torso' in self.norm_item:
                # used in JhmdbDataset
                torso_size_ = np.linalg.norm(gt_coords[0][4] - gt_coords[0][5])
                if torso_size_ < 1:
                    torso_size_ = np.linalg.norm(pred_coords[0][4] -
                                                 pred_coords[0][5])
                    warnings.warn('Ground truth torso size < 1. '
                                  'Use torso size from predicted '
                                  'keypoint results instead.')
                torso_size = np.array([torso_size_,
                                       torso_size_]).reshape(-1, 2)
                result['torso_size'] = torso_size

            self.results.append(result)

    def compute_metrics(self, results: list) -> Dict[str, float]:
        """Compute the metrics from processed results.

        Args:
            results (list): The processed results of each batch.

        Returns:
            Dict[str, float]: The computed metrics. The keys are the names of
            the metrics, and the values are corresponding results.
        """
        logger: MMLogger = MMLogger.get_current_instance()

        # pred_coords: [N, K, D]
        pred_coords = np.concatenate(
            [result['pred_coords'] for result in results])
        # gt_coords: [N, K, D]
        gt_coords = np.concatenate([result['gt_coords'] for result in results])
        # mask: [N, K]
        mask = np.concatenate([result['mask'] for result in results])

        metrics = dict()
        if 'bbox' in self.norm_item:
            norm_size_bbox = np.concatenate(
                [result['bbox_size'] for result in results])

            logger.info(f'Evaluating {self.__class__.__name__} '
                        f'(normalized by ``"bbox_size"``)...')

            _, pck, _ = keypoint_pck_accuracy(pred_coords, gt_coords, mask,
                                              self.thr, norm_size_bbox)
            metrics[f'@thr-{self.thr}'] = pck

        if 'head' in self.norm_item:
            norm_size_head = np.concatenate(
                [result['head_size'] for result in results])

            logger.info(f'Evaluating {self.__class__.__name__} '
                        f'(normalized by ``"head_size"``)...')

            _, pckh, _ = keypoint_pck_accuracy(pred_coords, gt_coords, mask,
                                               self.thr, norm_size_head)
            metrics[f'PCKh@thr-{self.thr}'] = pckh

        if 'torso' in self.norm_item:
            norm_size_torso = np.concatenate(
                [result['torso_size'] for result in results])

            logger.info(f'Evaluating {self.__class__.__name__} '
                        f'(normalized by ``"torso_size"``)...')

            pck_p, pckh, _ = keypoint_pck_accuracy(pred_coords, gt_coords,
                                                   mask, self.thr,
                                                   norm_size_torso)
            stats_names = [
                'Head', 'Sho', 'Elb', 'Wri', 'Hip', 'Knee', 'Ank', 'Mean'
            ]
            stats = [
                pck_p[2], 0.5 * pck_p[3] + 0.5 * pck_p[4],
                0.5 * pck_p[7] + 0.5 * pck_p[8],
                0.5 * pck_p[11] + 0.5 * pck_p[12],
                0.5 * pck_p[5] + 0.5 * pck_p[6],
                0.5 * pck_p[9] + 0.5 * pck_p[10],
                0.5 * pck_p[13] + 0.5 * pck_p[14], pck
            ]

            for stats_name, stat in zip(stats_names, stats):
                metrics[stats_name + f'@thr-{self.thr}'] = stat

        return metrics


@METRICS.register_module()
class AUC(BaseMetric):
    """AUC evaluation metric.

    Calculate the Area Under Curve (AUC) of keypoint PCK accuracy.

    By altering the threshold percentage in the calculation of PCK accuracy,
    AUC can be generated to further evaluate the pose estimation algorithms.

    Note:
        - length of dataset: N
        - num_keypoints: K
        - number of keypoint dimensions: D (typically D = 2)

    Args:
        norm_factor (float): AUC normalization factor, Default: 30 (pixels).
        num_thrs (int): number of thresholds to calculate auc. Default: 20.
        collect_device (str): Device name used for collecting results from
            different ranks during distributed training. Must be ``'cpu'`` or
            ``'gpu'``. Default: ``'cpu'``.
        prefix (str, optional): The prefix that will be added in the metric
            names to disambiguate homonymous metrics of different evaluators.
            If prefix is not provided in the argument, ``self.default_prefix``
            will be used instead. Default: ``None``.
    """
    default_prefix: Optional[str] = 'auc'

    def __init__(self,
                 norm_factor: float = 30,
                 num_thrs: int = 20,
                 collect_device: str = 'cpu',
                 prefix: Optional[str] = None) -> None:
        super().__init__(collect_device=collect_device, prefix=prefix)
        self.norm_factor = norm_factor
        self.num_thrs = num_thrs

    def process(self, data_batch: Sequence[dict],
                predictions: Sequence[dict]) -> None:
        """Process one batch of data samples and predictions. The processed
        results should be stored in ``self.results``, which will be used to
        compute the metrics when all batches have been processed.

        Args:
            data_batch (Sequence[dict]): A batch of data
                from the dataloader.
            predictions (Sequence[dict]): A batch of outputs from
                the model.
        """
        for data, pred in zip(data_batch, predictions):
            # predicted keypoints coordinates, [1, K, D]
            pred_coords = pred['pred_instances']['keypoints'].cpu().numpy()
            # ground truth data_info
            gt = data['data_sample']['gt_instances']
            # ground truth keypoints coordinates, [1, K, D]
            gt_coords = gt['keypoints']
            # ground truth keypoints_visible, [1, K, 1]
            mask = gt['keypoints_visible'].reshape(1, -1)

            result = {
                'pred_coords': pred_coords,
                'gt_coords': gt_coords,
                'mask': mask,
            }

            self.results.append(result)

    def compute_metrics(self, results: list) -> Dict[str, float]:
        """Compute the metrics from processed results.

        Args:
            results (list): The processed results of each batch.

        Returns:
            Dict[str, float]: The computed metrics. The keys are the names of
            the metrics, and the values are corresponding results.
        """
        logger: MMLogger = MMLogger.get_current_instance()

        # pred_coords: [N, K, D]
        pred_coords = np.concatenate(
            [result['pred_coords'] for result in results])
        # gt_coords: [N, K, D]
        gt_coords = np.concatenate([result['gt_coords'] for result in results])
        # mask: [N, K]
        mask = np.concatenate([result['mask'] for result in results])

        logger.info(f'Evaluating {self.__class__.__name__}...')

        auc = keypoint_auc(pred_coords, gt_coords, mask, self.norm_factor,
                           self.num_thrs)

        metrics = dict()
        metrics[f'@{self.num_thrs}thrs'] = auc

        return metrics


@METRICS.register_module()
class EPE(BaseMetric):
    """EPE evaluation metric.

    Calculate the end-point error (EPE) of keypoints.

    Note:
        - length of dataset: N
        - num_keypoints: K
        - number of keypoint dimensions: D (typically D = 2)

    Args:
        collect_device (str): Device name used for collecting results from
            different ranks during distributed training. Must be ``'cpu'`` or
            ``'gpu'``. Default: ``'cpu'``.
        prefix (str, optional): The prefix that will be added in the metric
            names to disambiguate homonymous metrics of different evaluators.
            If prefix is not provided in the argument, ``self.default_prefix``
            will be used instead. Default: ``None``.
    """
    default_prefix: Optional[str] = 'epe'

    def process(self, data_batch: Sequence[dict],
                predictions: Sequence[dict]) -> None:
        """Process one batch of data samples and predictions. The processed
        results should be stored in ``self.results``, which will be used to
        compute the metrics when all batches have been processed.

        Args:
            data_batch (Sequence[dict]): A batch of data
                from the dataloader.
            predictions (Sequence[dict]): A batch of outputs from
                the model.
        """
        for data, pred in zip(data_batch, predictions):
            # predicted keypoints coordinates, [1, K, D]
            pred_coords = pred['pred_instances']['keypoints'].cpu().numpy()
            # ground truth data_info
            gt = data['data_sample']['gt_instances']
            # ground truth keypoints coordinates, [1, K, D]
            gt_coords = gt['keypoints']
            # ground truth keypoints_visible, [1, K, 1]
            mask = gt['keypoints_visible'].reshape(1, -1)

            result = {
                'pred_coords': pred_coords,
                'gt_coords': gt_coords,
                'mask': mask,
            }

            self.results.append(result)

    def compute_metrics(self, results: list) -> Dict[str, float]:
        """Compute the metrics from processed results.

        Args:
            results (list): The processed results of each batch.

        Returns:
            Dict[str, float]: The computed metrics. The keys are the names of
            the metrics, and the values are corresponding results.
        """
        logger: MMLogger = MMLogger.get_current_instance()

        # pred_coords: [N, K, D]
        pred_coords = np.concatenate(
            [result['pred_coords'] for result in results])
        # gt_coords: [N, K, D]
        gt_coords = np.concatenate([result['gt_coords'] for result in results])
        # mask: [N, K]
        mask = np.concatenate([result['mask'] for result in results])

        logger.info(f'Evaluating {self.__class__.__name__}...')

        epe = keypoint_epe(pred_coords, gt_coords, mask)

        metrics = dict()
        metrics['epe'] = epe

        return metrics


@METRICS.register_module()
class NME(BaseMetric):
    """NME evaluation metric.

    Calculate the normalized mean error (NME) of keypoints.

    Note:
        - length of dataset: N
        - num_keypoints: K
        - number of keypoint dimensions: D (typically D = 2)

    Args:
        norm_mode (str): The normalization mode. There are two valid modes:
            `'use_norm_item'` and `'keypoint_distance'`.
            When set as `'use_norm_item'`, should specify the argument
            `norm_item`, which represents the item in the datainfo that
            will be used as the normalization factor.
            When set as `'keypoint_distance'`, should specify the argument
            `keypoint_indices` that are used to calculate the keypoint
            distance as the normalization factor.
        norm_item (str, optional): The item in the datainfo used as the
            normalization factor. For example, `'box_size'` in `'AFLWDataset'`.
            Only valid when ``norm_mode`` is ``use_norm_item``.
            Default: ``None``.
        keypoint_indices (Sequence[int], optional): The keypoint indices used
            to calculate the keypoint distance as the normalization factor.
            Only valid when ``norm_mode`` is ``keypoint_distance``.
            If set as None, will use the default ``keypoint_indices`` in
            `DEFAULT_KEYPOINT_INDICES` for specific datasets, else use the
            given ``keypoint_indices`` of the dataset. Default: ``None``.
        collect_device (str): Device name used for collecting results from
            different ranks during distributed training. Must be ``'cpu'`` or
            ``'gpu'``. Default: ``'cpu'``.
        prefix (str, optional): The prefix that will be added in the metric
            names to disambiguate homonymous metrics of different evaluators.
            If prefix is not provided in the argument, ``self.default_prefix``
            will be used instead. Default: ``None``.
    """
    default_prefix: Optional[str] = 'nme'

    DEFAULT_KEYPOINT_INDICES = {
        'horse10': [0, 1],  # corresponding to `nose` and `eye` keypoints
        '300w':
        [36,
         45],  # corresponding to `right-most` and `left-most` eye keypoints
        'coco_wholebody_face':
        [36,
         45],  # corresponding to `right-most` and `left-most` eye keypoints
        'cofw':
        [8, 9],  # corresponding to `right-most` and `left-most` eye keypoints
        'wflw':
        [60,
         72],  # corresponding to `right-most` and `left-most` eye keypoints
    }

    def __init__(self,
                 norm_mode: str,
                 norm_item: Optional[str] = None,
                 keypoint_indices: Optional[Sequence[int]] = None,
                 collect_device: str = 'cpu',
                 prefix: Optional[str] = None) -> None:
        super().__init__(collect_device=collect_device, prefix=prefix)
        allowed_norm_modes = ['use_norm_item', 'keypoint_distance']
        if norm_mode not in allowed_norm_modes:
            raise KeyError("`norm_mode` should be 'use_norm_item' or "
                           f"'keypoint_distance', but got {norm_mode}.")

        self.norm_mode = norm_mode
        if self.norm_mode == 'use_norm_item':
            if not norm_item:
                raise KeyError('`norm_mode` is set to `"use_norm_item"`, '
                               'please specify the `norm_item` in the '
                               'datainfo used as the normalization factor.')
        self.norm_item = norm_item
        self.keypoint_indices = keypoint_indices

    def process(self, data_batch: Sequence[dict],
                predictions: Sequence[dict]) -> None:
        """Process one batch of data samples and predictions. The processed
        results should be stored in ``self.results``, which will be used to
        compute the metrics when all batches have been processed.

        Args:
            data_batch (Sequence[dict]): A batch of data
                from the dataloader.
            predictions (Sequence[dict]): A batch of outputs from
                the model.
        """
        for data, pred in zip(data_batch, predictions):
            # predicted keypoints coordinates, [1, K, D]
            pred_coords = pred['pred_instances']['keypoints'].cpu().numpy()
            # ground truth data_info
            gt = data['data_sample']['gt_instances']
            # ground truth keypoints coordinates, [1, K, D]
            gt_coords = gt['keypoints']
            # ground truth keypoints_visible, [1, K, 1]
            mask = gt['keypoints_visible'].reshape(1, -1)

            result = {
                'pred_coords': pred_coords,
                'gt_coords': gt_coords,
                'mask': mask,
            }

            if self.norm_item:
                assert self.norm_item in gt, f'The ground truth data info ' \
                    f'do not have the expected normalized factor ' \
                    f'"{self.norm_item}"'
                # ground truth norm_item
                result[self.norm_item] = np.array(gt[self.norm_item]).reshape(
                    [-1, 1])

            self.results.append(result)

    def compute_metrics(self, results: list) -> Dict[str, float]:
        """Compute the metrics from processed results.

        Args:
            results (list): The processed results of each batch.

        Returns:
            Dict[str, float]: The computed metrics. The keys are the names of
            the metrics, and the values are corresponding results.
        """
        logger: MMLogger = MMLogger.get_current_instance()

        # pred_coords: [N, K, D]
        pred_coords = np.concatenate(
            [result['pred_coords'] for result in results])
        # gt_coords: [N, K, D]
        gt_coords = np.concatenate([result['gt_coords'] for result in results])
        # mask: [N, K]
        mask = np.concatenate([result['mask'] for result in results])

        logger.info(f'Evaluating {self.__class__.__name__}...')
        metrics = dict()

        if self.norm_mode == 'use_norm_item':
            normalize_factor_ = np.concatenate(
                [result[self.norm_item] for result in results])
            # normalize_factor: [N, 2]
            normalize_factor = np.tile(normalize_factor_, [1, 2])
            nme = keypoint_nme(pred_coords, gt_coords, mask, normalize_factor)
            metrics[f'@{self.norm_item}'] = nme

        else:
            if self.keypoint_indices is None:
                # use default keypoint_indices in some datasets
                dataset_name = self.dataset_meta['dataset_name']
                if dataset_name not in self.DEFAULT_KEYPOINT_INDICES:
                    raise KeyError(
                        '`norm_mode` is set to `keypoint_distance`, and the '
                        'keypoint_indices is set to None, can not find the '
                        'keypoint_indices in `DEFAULT_KEYPOINT_INDICES`, '
                        'please specify `keypoint_indices` appropriately.')
                self.keypoint_indices = self.DEFAULT_KEYPOINT_INDICES[
                    dataset_name]
            else:
                assert len(self.keypoint_indices) == 2, 'The keypoint '\
                    'indices used for normalization should be a pair.'
                keypoint_id2name = self.dataset_meta['keypoint_id2name']
                dataset_name = self.dataset_meta['dataset_name']
                for idx in self.keypoint_indices:
                    assert idx in keypoint_id2name, f'The {dataset_name} '\
                        f'dataset does not contain the required '\
                        f'{idx}-th keypoint.'
            # normalize_factor: [N, 2]
            normalize_factor = self._get_normalize_factor(gt_coords=gt_coords)
            nme = keypoint_nme(pred_coords, gt_coords, mask, normalize_factor)
            metrics[f'@{self.keypoint_indices}'] = nme

        return metrics

    def _get_normalize_factor(self, gt_coords: np.ndarray) -> np.ndarray:
        """Get the normalize factor. generally inter-ocular distance measured
        as the Euclidean distance between the outer corners of the eyes is
        used.

        Args:
            gt_coords (np.ndarray[N, K, 2]): Groundtruth keypoint coordinates.

        Returns:
            np.ndarray[N, 2]: normalized factor
        """
        idx1, idx2 = self.keypoint_indices

        interocular = np.linalg.norm(
            gt_coords[:, idx1, :] - gt_coords[:, idx2, :],
            axis=1,
            keepdims=True)

        return np.tile(interocular, [1, 2])