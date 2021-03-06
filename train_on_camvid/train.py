# coding=utf-8
from __future__ import print_function
from __future__ import division

import tensorflow as tf
import numpy as np
import os
import input_data
import model.denseASPP as denseASPP
import model.densenet as DenseNet
import utils.utils as Utils


MAX_STEPS = 40000
CLASSES = denseASPP.CLASSES
HEIGHT = input_data.HEIGHT
WIDTH = input_data.WIDTH
BATCH_SIZE = 4
scale = 1e-5
KEEP_PROB = 0.9

saved_ckpt_path = './checkpoint/'
saved_summary_train_path = './summary/train/'
saved_summary_test_path = './summary/test/'

initial_lr = 0.001

#      ['Sky', 'Building', 'Pole', 'Road', 'Pavement', 'Tree', 'SignSymbol', 'Fence', 'Car', 'Pedestrian', 'Bicyclist']

weights = [6.125, 4.226, 34.69, 3.4, 13.663, 7.869, 32.22, 28.248, 14.47, 38.026, 37.092] #ENet_weighting


def weighted_loss(logits, labels, num_classes, head=None):
    """re-weighting"""
    with tf.name_scope('loss'):
        logits = tf.reshape(logits, (-1, num_classes))

        epsilon = tf.constant(value=1e-10)

        logits = logits + epsilon

        label_flat = tf.reshape(labels, (-1, 1))
        labels = tf.reshape(tf.one_hot(label_flat, depth=num_classes), (-1, num_classes))

        softmax = tf.nn.softmax(logits)

        cross_entropy = -tf.reduce_sum(tf.multiply(labels * tf.log(softmax + epsilon), head), axis=[1])

        cross_entropy_mean = tf.reduce_mean(cross_entropy, name='cross_entropy')

    return cross_entropy_mean

def cal_loss(logits, labels):

    loss_weight = weights
    loss_weight = np.array(loss_weight)

    labels = tf.cast(labels, tf.int32)

    return weighted_loss(logits, labels, num_classes=CLASSES, head=loss_weight)

with tf.name_scope("input"):

    x = tf.placeholder(tf.float32, [BATCH_SIZE, HEIGHT, WIDTH, 3], name='x_input')
    y = tf.placeholder(tf.int32, [BATCH_SIZE, HEIGHT, WIDTH], name='ground_truth')
    keep_prob = tf.placeholder(dtype=tf.float32, name='keep_prob')

logits = denseASPP.denseASPP(x, keep_prob, train=True)


with tf.name_scope('regularization'):
    regularizer = tf.contrib.layers.l2_regularizer(scale)
    reg_term = tf.contrib.layers.apply_regularization(regularizer)

with tf.name_scope("loss"):
    loss = cal_loss(logits=logits, labels=y)
    #loss = tf.reduce_mean(tf.nn.sparse_softmax_cross_entropy_with_logits(labels=y, logits=logits, name='loss'))
    loss_all = loss + reg_term
    #loss_all = loss
    tf.summary.scalar('loss', loss)
    tf.summary.scalar('loss_all', loss_all)

with tf.name_scope('learning_rate'):
    lr = tf.Variable(initial_lr, dtype=tf.float32)
    tf.summary.scalar('learning_rate', lr)

optimizer = tf.train.AdamOptimizer(lr).minimize(loss_all)


with tf.name_scope("mIoU"):
    softmax = tf.nn.softmax(logits, axis=-1)
    predictions = tf.argmax(logits, axis=-1, name='predictions')

    train_mIoU = tf.Variable(0, dtype=tf.float32)
    tf.summary.scalar('train_mIoU', train_mIoU)
    test_mIoU = tf.Variable(0, dtype=tf.float32)
    tf.summary.scalar('test_mIoU',test_mIoU)

merged = tf.summary.merge_all()

image_batch, anno_batch, filename = input_data.read_batch(BATCH_SIZE, type = 'trainval')
image_batch_test, anno_batch_test, filename_test = input_data.read_batch(BATCH_SIZE, type = 'test')

with tf.Session() as sess:

    coord = tf.train.Coordinator()
    threads = tf.train.start_queue_runners(sess=sess, coord=coord)

    sess.run(tf.local_variables_initializer())
    sess.run(tf.global_variables_initializer())

    saver = tf.train.Saver()

    #if os.path.exists(saved_ckpt_path):
    ckpt = tf.train.get_checkpoint_state(saved_ckpt_path)
    if ckpt and ckpt.model_checkpoint_path:
        saver.restore(sess, ckpt.model_checkpoint_path)
        print("Model restored...")

    #saver.restore(sess, './checkpoint/denseASPP.model-30000')

    train_summary_writer = tf.summary.FileWriter(saved_summary_train_path, sess.graph)
    test_summary_writer = tf.summary.FileWriter(saved_summary_test_path, sess.graph)



    for i in range(0, MAX_STEPS + 1):


        b_image, b_anno, b_filename = sess.run([image_batch, anno_batch, filename])

        b_image, b_anno = input_data.aug_std(b_image, b_anno, type='train')

        b_image_test, b_anno_test, b_filename_test = sess.run([image_batch_test, anno_batch_test, filename_test])

        b_image_test, b_anno_test = input_data.aug_std(b_image_test, b_anno_test, type='test')

        _ = sess.run(optimizer, feed_dict={x: b_image, y: b_anno, keep_prob: KEEP_PROB})
        train_summary = sess.run(merged, feed_dict={x: b_image, y: b_anno, keep_prob: 1.0})
        train_summary_writer.add_summary(train_summary, i)
        test_summary = sess.run(merged, feed_dict={x: b_image_test, y: b_anno_test, keep_prob: 1.0})
        test_summary_writer.add_summary(test_summary, i)

        pred_train, train_loss_val_all, train_loss_val = sess.run([predictions, loss_all, loss], feed_dict={x: b_image, y: b_anno, keep_prob: 1.0})
        pred_test, test_loss_val_all, test_loss_val = sess.run([predictions, loss_all, loss], feed_dict={x: b_image_test, y: b_anno_test, keep_prob: 1.0})

        learning_rate = sess.run(lr)

        if i % 10 == 0:
            print("train step: %d, learning rate: %f, train loss all: %f, train loss: %f, test loss all: %f, test loss: %f" %(i, learning_rate, train_loss_val_all, train_loss_val, test_loss_val_all, test_loss_val))

        if i % 200 == 0:

            train_mIoU_val, train_IoU_val = Utils.cal_batch_mIoU(pred_train, b_anno, CLASSES)
            test_mIoU_val, test_IoU_val = Utils.cal_batch_mIoU(pred_test, b_anno_test, CLASSES)

            sess.run(tf.assign(train_mIoU, train_mIoU_val))
            sess.run(tf.assign(test_mIoU, test_mIoU_val))

            print("train step: %d, learning rate: %f, train loss all: %f, train loss: %f, train mIoU: %f, test loss all: %f, test loss: %f, test mIoU: %f," %(i, learning_rate, train_loss_val_all, train_loss_val, train_mIoU_val, test_loss_val_all, test_loss_val, test_mIoU_val))
            print(train_IoU_val)
            print(test_IoU_val)

        if i % 2000 == 0:
            saver.save(sess, os.path.join(saved_ckpt_path, 'denseASPP.model'), global_step=i)

        if i != 0 and i % 4000 == 0:
            sess.run(tf.assign(lr, 0.7 * lr))


    coord.request_stop()
    coord.join(threads)
