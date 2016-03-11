"""Trains, Evaluates and Saves the model network using a Queue."""
# pylint: disable=missing-docstring
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os.path
import time
import logging
import sys
import numpy
import imp
from shutil import copyfile

import tensorflow.python.platform
from six.moves import xrange  # pylint: disable=redefined-builtin
import tensorflow as tf
 
import utils as utils

flags = tf.app.flags
FLAGS = flags.FLAGS


#configure logging

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s',
                    level=logging.DEBUG,
                    stream=sys.stdout)



def _copy_parameters_to_traindir(input_file, target_name, target_dir):
  """Helper to copy files defining the network to the saving dir.

  Args:
    input_file: name of source file
    target_name: target name
    traindir: directory where training data is saved
  """
  target_file = os.path.join(target_dir, target_name)
  copyfile(input_file, target_file)
    
    
def initialize_training_folder(train_dir):
  """Creating the training folder and copy all model files into it.

  The model will be executed from the training folder and all
  outputs will be saved there.

  Args:
    train_dir: The training folder
  """

  target_dir = os.path.join(train_dir, "model_files")  
  if not os.path.exists(target_dir):
    os.makedirs(target_dir)

  # Creating an additional logging saving the console outputs
  # into the training folder
  logging_file = os.path.join(train_dir, "output.log")
  filewriter = logging.FileHandler(logging_file, mode='w')
  formatter = logging.Formatter('%(asctime)s %(name)-3s %(levelname)-3s %(message)s')
  filewriter.setLevel(logging.INFO)
  filewriter.setFormatter(formatter)
  logging.getLogger('').addHandler(filewriter)

  #TODO: read more about loggers and make file logging neater.


  config_file = tf.app.flags.FLAGS.config
  params = imp.load_source("params", config_file)  
  _copy_parameters_to_traindir(config_file, "params.py", target_dir)
  _copy_parameters_to_traindir(params.input_file, "input.py", target_dir)
  _copy_parameters_to_traindir(params.network_file, "network.py", target_dir)
  _copy_parameters_to_traindir(params.opt_file, "optimizer.py", target_dir)


def maybe_download_and_extract(train_dir):
  target_dir = os.path.join(train_dir, "model_files")  
  data_input = imp.load_source("input", os.path.join(target_dir, "input.py"))
  data_input.maybe_download_and_extract(utils.cfg.data_dir)


def write_precision_to_summary(precision, summary_writer, name, global_step, sess):
  #write result to summary
  summary = tf.Summary()
  #summary.ParseFromString(sess.run(summary_op))
  summary.value.add(tag='Evaluation/' + name + ' Precision',
                    simple_value=precision)
  summary_writer.add_summary(summary, global_step)


def run_training(train_dir):
  """Train model for a number of steps."""
  # Get the sets of images and labels for training, validation, and
  # test on MNIST.

  # Tell TensorFlow that the model will be built into the default Graph.


  target_dir = os.path.join(train_dir, "model_files")  
  data_input = imp.load_source("input", os.path.join(target_dir, "input.py"))
  network = imp.load_source("network", os.path.join(target_dir, "network.py"))
  opt = imp.load_source("objective", os.path.join(target_dir, "optimizer.py"))
  params = imp.load_source("params", os.path.join(target_dir, "params.py"))

  with tf.Graph().as_default():

    global_step = tf.Variable(0.0, trainable=False)

    with tf.name_scope('Input'):
      image_batch, label_batch = data_input.distorted_inputs(utils.cfg.data_dir,
                                                             params.batch_size)

    # Build a Graph that computes predictions from the inference network.
    logits = network.inference(image_batch, train=True)

    # Build Graph for Validation. This Graph shares Variabels with
    # the training Graph
    with tf.name_scope('Validation'):
      with tf.name_scope('Input_train_data'):
        image_batch_val, label_batch_val = data_input.distorted_inputs(
                                                               utils.cfg.data_dir,
                                                               params.batch_size)
      with tf.name_scope('Input_val_data'):  
        image_batch_train, label_batch_train = data_input.inputs(False,
                                                               utils.cfg.data_dir,
                                                               params.batch_size)
      with tf.name_scope('Input_test_data'):  
        image_batch_test, label_batch_test = data_input.inputs(True,
                                                               utils.cfg.data_dir,
                                                               params.batch_size)

      #activate the reuse of Variabels  
      tf.get_variable_scope().reuse_variables()

      #Build Networks for Validation and Evaluation Data
      logits_train = network.inference(image_batch_train, train=False)
      logits_val = network.inference(image_batch_val, train=False)
      logits_test = network.inference(image_batch_test, train=False)
    


    # Add to the Graph the Ops for loss calculation.
    loss = network.loss(logits, label_batch)

    # Add to the Graph the Ops that calculate and apply gradients.
    train_op = opt.training(loss, global_step=global_step,
                            learning_rate=params.learning_rate)

    # Add the Op to compare the logits to the labels during evaluation.
    eval_train = network.evaluation(logits_train, label_batch_train)
    eval_val = network.evaluation(logits_val, label_batch_val)
    eval_test = network.evaluation(logits_test, label_batch_test)
    eval_correct = network.evaluation(logits, label_batch)

    # Build the summary operation based on the TF collection of Summaries.
    summary_op = tf.merge_all_summaries()

    # Create a saver for writing training checkpoints.
    saver = tf.train.Saver()

    # Create a session for running Ops on the Graph.
    sess = tf.Session()

    # Run the Op to initialize the variables.
    init = tf.initialize_all_variables()
    sess.run(init)

    # Start the queue runners.
    tf.train.start_queue_runners(sess=sess)

    # Instantiate a SummaryWriter to output summaries and the Graph.
    summary_writer = tf.train.SummaryWriter(train_dir,
                                            graph_def=sess.graph_def)

    # And then after everything is built, start the training loop.
    for step in xrange(params.max_steps):
      start_time = time.time()

      # Run one step of the model.  The return values are the activations
      # from the `train_op` (which is discarded) and the `loss` Op.  To
      # inspect the values of your Ops or variables, you may include them
      # in the list passed to sess.run() and the value tensors will be
      # returned in the tuple from the call.
      _, loss_value = sess.run([train_op, loss])

      # Write the summaries and print an overview fairly often.
      if step % 100 == 0:
        # Print status to stdout.
        duration = time.time() - start_time
        examples_per_sec = params.batch_size / duration
        sec_per_batch = float(duration)
        logging.info('Step %d: loss = %.2f ( %.3f sec (per Batch); %.1f examples/sec;)'
                                     % (step, loss_value,
                                     sec_per_batch, examples_per_sec))
        # Update the events file.
        summary_str = sess.run(summary_op)
        summary_writer.add_summary(summary_str, step)

      # Save a checkpoint and evaluate the model periodically.
      if (step+1) % 1000 == 0 or (step + 1) == params.max_steps:
        checkpoint_path = os.path.join(train_dir, 'model.ckpt')
        saver.save(sess, checkpoint_path , global_step=step)
        # Evaluate against the training set.

      if (step+1) % 1000 == 0 or (step + 1) == params.max_steps:                                   
        logging.info('Doing Evaluate with whole epoche of Training Data:')
        precision= utils.do_eval(sess,
                                 eval_train,
                                 params.num_examples_per_epoch_for_train,
                                 params,
                                 name="Train")
        write_precision_to_summary(precision, summary_writer,"Train" , step, sess)
    
        #logging.info('Validation Data Eval:')
        #TODO: Analyse Validation Error.
        #precision= utils.do_eval(sess,
        #                         eval_val,
        #                         params.num_examples_per_epoch_for_train,
        #                         params,
        #                         name="Val")
        #write_precision_to_summary(precision, summary_writer,"Val" , step, sess)

        logging.info('Doing Evaluation with Testing Data')
        precision= utils.do_eval(sess,
                                 eval_test,
                                 params.num_examples_per_epoch_for_eval,
                                 params,
                                 name="Test")
        write_precision_to_summary(precision, summary_writer,"Test" , step, sess)

    
def main(_):
  if FLAGS.config == "example_params.py":
    logging.info("Training on default config.")
    logging.info("Use training.py --config=your_config.py to train different models")

  train_dir = utils.get_train_dir()
  initialize_training_folder(train_dir)
  maybe_download_and_extract(train_dir)
  run_training(train_dir)



if __name__ == '__main__':
  tf.app.run()
