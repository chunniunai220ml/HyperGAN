import argparse
import os
import tensorflow as tf
import hypergan as hg
import hyperchamber as hc
from hypergan.loaders import *
from hypergan.samplers.common import *
from hypergan.util.globals import *


def parse_args():
    parser = argparse.ArgumentParser(description='Train a colorizer!', add_help=True)
    parser.add_argument('directory', action='store', type=str, help='The location of your data.  Subdirectories are treated as different classes.  You must have at least 1 subdirectory.')
    parser.add_argument('--batch_size', '-b', type=int, default=32, help='Number of samples to include in each batch.  If using batch norm, this needs to be preserved when in server mode')
    parser.add_argument('--crop', type=bool, default=False, help='If your images are perfectly sized you can skip cropping.')
    parser.add_argument('--device', '-d', type=str, default='/gpu:0', help='In the form "/gpu:0", "/cpu:0", etc.  Always use a GPU (or TPU) to train')
    parser.add_argument('--format', '-f', type=str, default='png', help='jpg or png')
    parser.add_argument('--sample_every', type=int, default=50, help='Samples the model every n epochs.')
    parser.add_argument('--save_every', type=int, default=30000, help='Saves the model every n epochs.')
    parser.add_argument('--size', '-s', type=str, default='64x64x3', help='Size of your data.  For images it is widthxheightxchannels.')
    parser.add_argument('--use_hc_io', type=bool, default=False, help='Set this to no unless you are feeling experimental.')
    return parser.parse_args()

x = None
z = None
def sampler(name, sess, config):
    generator = get_tensor("g")[0]
    y_t = get_tensor("y")
    z_t = get_tensor("z")
    x_t = get_tensor('x')
    mask_t = get_tensor('mask')
    fltr_x_t = get_tensor('xfiltered')
    global x
    global z
    if(x == None):
        x, z = sess.run([x_t, z_t])

    x_tiled = np.tile(x[0][0], [config['batch_size'],1,1,1])

    s = [int(x) for x in mask_t.get_shape()]
    #mask = np.zeros([s[0], s[1]//2, s[2]//2, s[3]])
    #constants = (1,1)
    #mask = np.pad(mask, ((0,0),(s[1]//4,s[1]//4),(s[2]//4,s[2]//4),(0,0)),'constant', constant_values=constants)
    print("Set up mask")

    sample, bw_x = sess.run([generator, fltr_x_t], {x_t: x_tiled, z_t: z})#, mask_t: mask})
    stacks = []
    stacks.append([x_tiled[0], bw_x[0], sample[0], sample[1], sample[2], sample[3]])
    for i in range(4):
        stacks.append([sample[i*6+4+j] for j in range(6)])
    
    images = np.vstack([np.hstack(s) for s in stacks])
    plot(config, images, name)

def add_inpaint(gan, net):
    x = get_tensor('x')
    mask = get_tensor('mask')
    s = [int(x) for x in net.get_shape()]
    shape = [s[1], s[2]]
    x = tf.image.resize_images(x, shape, 1)
    mask = tf.image.resize_images(mask, shape, 1)
    print("Created bw ", x)

    x = x*mask#tf.image.rgb_to_grayscale(x)
    #x += tf.random_normal(x.get_shape(), mean=0, stddev=1e-1, dtype=config['dtype'])

    return x


def add_original_x(gan, net):
    x = get_tensor('x')
    mask = get_tensor('mask')

    s = [int(x) for x in net.get_shape()]
    shape = [s[1], s[2]]
    mask = tf.image.resize_images(mask, shape, 1)

    x = tf.image.resize_images(x, shape, 1)
    #xx += tf.random_normal(xx.get_shape(), mean=0, stddev=config['noise_stddev'], dtype=root_config['dtype'])
    x = x*mask
    return x

args = parse_args()

width = int(args.size.split("x")[0])
height = int(args.size.split("x")[1])
channels = int(args.size.split("x")[2])

selector = hg.config.selector(args)

config = selector.random_config()
config_filename = os.path.expanduser('~/.hypergan/configs/inpainting.json')
config = selector.load_or_create_config(config_filename, config)

#TODO add this option to D
#TODO add this option to G
config['generator.layer_filter'] = add_inpaint
config['discriminators'][0]['layer_filter'] = add_original_x

# TODO refactor, shared in CLI
config['dtype']=tf.float32
config['batch_size'] = args.batch_size
x,y,f,num_labels,examples_per_epoch = image_loader.labelled_image_tensors_from_directory(
                        args.directory,
                        config['batch_size'], 
                        channels=channels, 
                        format=args.format,
                        crop=args.crop,
                        width=width,
                        height=height)

config['y_dims']=num_labels
config['x_dims']=[height,width]
config['channels']=channels
config['model']='inpainting'
config = hg.config.lookup_functions(config)

initial_graph = {
    'x':x,
    'y':y,
    'f':f,
    'num_labels':num_labels,
    'examples_per_epoch':examples_per_epoch
}


shape = [config['batch_size'], config['x_dims'][0], config['x_dims'][1], config['channels']]
mask = tf.ones([shape[1], shape[2], shape[3]])
scaling = 0.6
mask = tf.image.central_crop(mask, scaling)
print(mask.get_shape())
left = (shape[1]*scaling)//2 * 0.75
top = (shape[2]*scaling)//2 * 0.75
mask = tf.image.pad_to_bounding_box(mask, int(top), int(left), shape[1], shape[2])
mask = (1.0-mask)
#mask = tf.random_uniform(shape, -1, 1)
#mask = tf.greater(mask, 0)
mask = tf.cast(mask, tf.float32)
set_tensor('mask', mask)

gan = hg.GAN(config, initial_graph)

save_file = os.path.expanduser("~/.hypergan/saves/inpainting.ckpt")
gan.load_or_initialize_graph(save_file)

tf.train.start_queue_runners(sess=gan.sess)
for i in range(100000):
    d_loss, g_loss = gan.train()

    if i % args.save_every == 0 and i > 0:
        print("Saving " + save_file)
        gan.save(save_file)

    if i % args.sample_every == 0 and i > 0:
        print("Sampling "+str(i))
        sample_file = "samples/"+str(i)+".png"
        gan.sample_to_file(sample_file, sampler=sampler)
        if args.use_hc_io:
            hc.io.sample(config, [{"image":sample_file, "label": 'sample'}]) 

tf.reset_default_graph()
self.sess.close()
