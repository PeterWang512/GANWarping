python train.py --dataroot data/sg3r_horse/horse_purple_fur --name horse_purple_fur --only_weight --rank 50 --lr_rampdown_length 0.5 --lr_schedule karras --update_layers 14 --trainer color --pretrained_G pretrained/stylegan3-r-horse-256x256.pkl --max_iter 2000 --lr 0.05 --batch_size 8 --evaluation_metrics trainproject,trainsample --lambda_l1_clr 1