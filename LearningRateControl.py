
import os
from Util import betterRepr, simpleObjRepr, ObjAsDict


class LearningRateControl(object):

  class EpochData:
    def __init__(self, learningRate, error=None):
      """
      :type learningRate: float
      :type error: dict[str,float] | None
      """
      self.learningRate = learningRate
      if isinstance(error, float):  # Old format.
        error = {"old_format_score": error}
      if error is None:
        error = {}
      self.error = error

    __repr__ = simpleObjRepr

  @classmethod
  def load_initial_kwargs_from_config(cls, config):
    """
    :type config: Config.Config
    :rtype: dict[str]
    """
    return {
      "initialLearningRate": config.float('learning_rate', 1.0),
      "errorMeasureKey": config.value('learning_rate_control_error_measure', None),
      "filename": config.value('learning_rate_file', None)}

  @classmethod
  def load_initial_from_config(cls, config):
    """
    :type config: Config.Config
    :rtype: LearningRateControl
    """
    kwargs = cls.load_initial_kwargs_from_config(config)
    return cls(**kwargs)

  def __init__(self, initialLearningRate, errorMeasureKey=None, filename=None):
    """
    :param float initialLearningRate: learning rate for epoch 1
    :param str errorMeasureKey: for getEpochErrorValue() the selector for EpochData.error which is a dict
    :param str filename: load from and save to file
    """
    self.epochData = {1: self.EpochData(initialLearningRate)}
    self.initialLearningRate = initialLearningRate
    self.errorMeasureKey = errorMeasureKey
    self.filename = filename
    if filename and os.path.exists(filename):
      self.load()

  __repr__ = simpleObjRepr

  def __str__(self):
    return "%r, epoch data: %s" % \
           (self, ", ".join(["%i: %s" % (epoch, self.epochData[epoch])
                             for epoch in sorted(self.epochData.keys())]))

  def calcLearningRateForEpoch(self, epoch):
    """
    :type epoch: int
    :returns learning rate
    :rtype: float
    """
    raise NotImplementedError

  def getLearningRateForEpoch(self, epoch):
    """
    :type epoch: int
    :rtype: float
    """
    assert epoch >= 1
    if epoch in self.epochData: return self.epochData[epoch].learningRate
    learningRate = self.calcLearningRateForEpoch(epoch)
    self.setLearningRateForEpoch(epoch, learningRate)
    return learningRate

  def setLearningRateForEpoch(self, epoch, learningRate):
    """
    :type epoch: int
    :type learningRate: float
    """
    if epoch in self.epochData:
      self.epochData[epoch].learningRate = learningRate
    else:
      self.epochData[epoch] = self.EpochData(learningRate)

  def getLastEpoch(self, epoch):
    epochs = sorted([e for e in self.epochData.keys() if e < epoch])
    if not epochs:
      return None
    return epochs[-1]

  def setEpochError(self, epoch, error):
    """
    :type epoch: int
    :type error: dict[str,float]
    """
    assert epoch in self.epochData, "You did not called getLearningRateForEpoch(%i)?" % epoch
    assert isinstance(error, dict)
    self.epochData[epoch].error.update(error)

  def getErrorKey(self):
    if self.errorMeasureKey:
      return self.errorMeasureKey
    if not self.epochData:
      return None
    first_epoch = self.epochData[min(self.epochData.keys())]
    if not first_epoch.error:
      return None
    if len(first_epoch.error) == 1:
      return min(first_epoch.error.keys())
    for key in ["dev_score", "train_score"]:  # To keep old setups producing the same behavior, keep this order.
      if key in first_epoch.error:
        return key
    return min(first_epoch.error.keys())

  def getEpochErrorValue(self, epoch):
    key = self.getErrorKey()
    assert key
    error = self.epochData[epoch].error
    assert key in error, "%r not in %r. fix %r in config. set it to %r or so." % \
                         (key, error, 'learning_rate_control_error_measure', 'dev_error')
    return error[key]

  def save(self):
    if not self.filename: return
    f = open(self.filename, "w")
    f.write(betterRepr(self.epochData))
    f.write("\n")
    f.close()

  def load(self):
    s = open(self.filename).read()
    self.epochData = eval(s, {}, ObjAsDict(self))


class ConstantLearningRate(LearningRateControl):

  def calcLearningRateForEpoch(self, epoch):
    """
    Dummy constant learning rate. Returns initial learning rate.
    :type epoch: int
    :returns learning rate
    :rtype: float
    """
    return self.initialLearningRate


class NewbobRelative(LearningRateControl):

  @classmethod
  def load_initial_kwargs_from_config(cls, config):
    """
    :type config: Config.Config
    :rtype: dict[str]
    """
    kwargs = super(NewbobRelative, cls).load_initial_kwargs_from_config(config)
    kwargs.update({
      "relativeErrorThreshold": config.float('newbob_relative_error_threshold', -0.01),
      "learningRateDecayFactor": config.float('newbob_learning_rate_decay', 0.5)})
    return kwargs

  def __init__(self, relativeErrorThreshold, learningRateDecayFactor, **kwargs):
    """
    :param float initialLearningRate: learning rate for epoch 1+2
    :type relativeErrorThreshold: float
    :type learningRateDecayFactor: float
    :type filename: str
    """
    super(NewbobRelative, self).__init__(**kwargs)
    self.relativeErrorThreshold = relativeErrorThreshold
    self.learningRateDecayFactor = learningRateDecayFactor

  def calcLearningRateForEpoch(self, epoch):
    """
    Newbob+ on train data.
    :type epoch: int
    :returns learning rate
    :rtype: float
    """
    lastEpoch = self.getLastEpoch(epoch)
    if lastEpoch is None:
      return self.initialLearningRate
    learningRate = self.epochData[lastEpoch].learningRate
    if learningRate is None:
      return self.initialLearningRate
    last2Epoch = self.getLastEpoch(lastEpoch)
    if last2Epoch is None:
      return learningRate
    oldError = self.getEpochErrorValue(last2Epoch)
    newError = self.getEpochErrorValue(lastEpoch)
    if oldError is None or newError is None:
      return learningRate
    relativeError = (newError - oldError) / abs(newError)
    if relativeError > self.relativeErrorThreshold:
      learningRate *= self.learningRateDecayFactor
    return learningRate


class NewbobAbs(LearningRateControl):

  @classmethod
  def load_initial_kwargs_from_config(cls, config):
    """
    :type config: Config.Config
    :rtype: dict[str]
    """
    kwargs = super(NewbobAbs, cls).load_initial_kwargs_from_config(config)
    kwargs.update({
      "errorThreshold": config.float('newbob_error_threshold', -0.01),
      "learningRateDecayFactor": config.float('newbob_learning_rate_decay', 0.5)})
    return kwargs

  def __init__(self, errorThreshold, learningRateDecayFactor, **kwargs):
    """
    :type errorThreshold: float
    :type learningRateDecayFactor: float
    """
    super(NewbobAbs, self).__init__(**kwargs)
    self.errorThreshold = errorThreshold
    self.learningRateDecayFactor = learningRateDecayFactor

  def calcLearningRateForEpoch(self, epoch):
    """
    Newbob+ on train data.
    :type epoch: int
    :returns learning rate
    :rtype: float
    """
    lastEpoch = self.getLastEpoch(epoch)
    if lastEpoch is None:
      return self.initialLearningRate
    learningRate = self.epochData[lastEpoch].learningRate
    if learningRate is None:
      return self.initialLearningRate
    last2Epoch = self.getLastEpoch(lastEpoch)
    if last2Epoch is None:
      return learningRate
    oldError = self.getEpochErrorValue(last2Epoch)
    newError = self.getEpochErrorValue(lastEpoch)
    if oldError is None or newError is None:
      return learningRate
    errorDiff = newError - oldError
    if errorDiff > self.errorThreshold:
      learningRate *= self.learningRateDecayFactor
    return learningRate


def learningRateControlType(typeName):
  if typeName == "constant":
    return ConstantLearningRate
  elif typeName in ("newbob", "newbob_rel", "newbob_relative"):  # Old setups expect the relative version.
    return NewbobRelative
  elif typeName == "newbob_abs":
    return NewbobAbs
  else:
    assert False, "unknown learning-rate-control type %s" % typeName


def loadLearningRateControlFromConfig(config):
  """
  :type config: Config.Config
  :rtype: LearningRateControl
  """
  controlType = config.value("learning_rate_control", "constant")
  cls = learningRateControlType(controlType)
  return cls.load_initial_from_config(config)

