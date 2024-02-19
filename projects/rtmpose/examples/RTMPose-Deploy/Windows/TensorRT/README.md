# rtmpose_tensorrt

## Description

This repository is use the TensorRT to deploy RTMDet and RTMPose. Your computer should have these components:

- NVIDIA GPU
- CUDA
- cudnn
- TensorRT 8.x
- OPENCV
- VS2019

The effect of the code is as follows:

![mabaoguo](https://github.com/Dominic23331/rtmpose_tensorrt/assets/53283758/568563be-a31d-4d03-9629-842dad3745e2)

## Get Started

### I. Convert Model

#### 1. RTMDet

When you start to convert a RTMDet model, you can use **convert_rtmdet.py** to convert pth file to onnx.

```shell
python convert_rtmdet.py --config <model cfg> --checkpoint <checkpoint> --output <output path>
```

Note that RTMDet should be the mmdetection version, and the conversion of mmyolo is not supported.

#### 2. RTMPose

You can use mmdeploy to convert RTMPose. The mmdeploy config file should use **configs/mmpose/pose-detection_simcc_onnxruntime_dynamic.py**.  The convert command as follow:

```shell
python tools/deploy.py <deploy cfg> <model cfg> <checkpoint> <image path>
```

#### 3. Convert to TensorRT engine file

You can use trtexec to convert an ONNX file to engine file. The command as follow:

```
trtexec --onnx=<ONNX file> --saveEngine=<output file>
```

**Note that the engine files included in the project are only for storing examples. As the engine files generated by TensorRT are related to hardware, it is necessary to regenerate the engine files on the computer where the code needs to be run.**

### II. Run

At first, you should fill in the model locations for RTMDet and RTMPose as follows:

```c++
// set engine file path
string detEngineFile = "./model/rtmdet.engine";
string poseEngineFile = "./model/rtmpose_m.engine";
```

Then, you can set the cap to video file or camera.

```
// open cap
cv::VideoCapture cap(0);
```

If you want to change iou threshold or confidence threshold, you can change them when you initialize RTMDet model.

```
RTMDet det_model(detEngineFile, logger, 0.5, 0.65);
```

Finally, you can run the **main.cpp** file to get result.