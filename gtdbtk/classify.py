###############################################################################
#                                                                             #
#    This program is free software: you can redistribute it and/or modify     #
#    it under the terms of the GNU General Public License as published by     #
#    the Free Software Foundation, either version 3 of the License, or        #
#    (at your option) any later version.                                      #
#                                                                             #
#    This program is distributed in the hope that it will be useful,          #
#    but WITHOUT ANY WARRANTY; without even the implied warranty of           #
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            #
#    GNU General Public License for more details.                             #
#                                                                             #
#    You should have received a copy of the GNU General Public License        #
#    along with this program. If not, see <http://www.gnu.org/licenses/>.     #
#                                                                             #
###############################################################################

import os
import sys
import shutil
import logging
import tempfile
import random

from collections import defaultdict

from biolib.common import remove_extension, make_sure_path_exists
from biolib.seq_io import read_seq, read_fasta
from biolib.newick import parse_label
from biolib.external.execute import check_dependencies
from biolib.taxonomy import Taxonomy

from tools import add_ncbi_prefix, merge_two_dicts
from relative_distance import RelativeDistance

import config.config as Config

import dendropy

from numpy import median as np_median

sys.setrecursionlimit(1500)

class Classify():
    """Determine taxonomic classification of genomes by ML placement."""

    def __init__(self, cpus=1):
        """Initialize."""
                
        check_dependencies(['pplacer', 'guppy', 'mash'])
        
        self.taxonomy_file = Config.TAXONOMY_FILE
        
        self.order_rank=["d__","p__","c__","o__",'f__','g__']
        
        self.logger = logging.getLogger('timestamp') 
        self.cpus = cpus

    def place_genomes(self, 
                        user_msa_file, 
                        marker_set_id, 
                        out_dir, 
                        prefix):
        """Place genomes into reference tree using pplacer."""
        
        # rename user MSA file for compatibility with pplacer
        if not user_msa_file.endswith('.fasta'):
            t = os.path.join(out_dir, prefix + '.user_msa.fasta')
            shutil.copyfile(user_msa_file, t)
            user_msa_file = t
              
        # run pplacer to place bins in reference genome tree
        num_genomes = sum([1 for _seq_id, _seq in read_seq(user_msa_file)])

        # get path to pplacer reference package   
        if marker_set_id == 'bac120':
            self.logger.info('Placing %d bacterial genomes into reference tree with pplacer (be patient).' % num_genomes)
            pplacer_ref_pkg = os.path.join(Config.PPLACER_DIR, Config.PPLACER_BAC120_REF_PKG)
        elif marker_set_id == 'ar122':
            self.logger.info('Placing %d archaeal genomes into reference tree with pplacer (be patient).' % num_genomes)
            pplacer_ref_pkg = os.path.join(Config.PPLACER_DIR, Config.PPLACER_AR122_REF_PKG)
        elif marker_set_id == 'rps23':
            self.logger.info('Placing %d genomes into reference tree with pplacer (be patient).' % num_genomes)
            pplacer_ref_pkg = os.path.join(Config.PPLACER_DIR, Config.PPLACER_RPS23_REF_PKG)

        pplacer_out_dir = os.path.join(out_dir, 'pplacer')
        if not os.path.exists(pplacer_out_dir):
            os.makedirs(pplacer_out_dir)
            
        pplacer_out = os.path.join(pplacer_out_dir, 'pplacer.%s.out' % marker_set_id)
        pplacer_json_out = os.path.join(pplacer_out_dir, 'pplacer.%s.json' % marker_set_id)
        cmd = 'pplacer -j %d -c %s -o %s %s > %s' % (self.cpus,
                                                     pplacer_ref_pkg,
                                                     pplacer_json_out,
                                                     user_msa_file,
                                                     pplacer_out)
        #os.system(cmd)

        # extract tree
        tree_file = os.path.join(out_dir, prefix + ".%s.classify.tree" % marker_set_id)
        cmd = 'guppy tog -o %s %s' % (tree_file, pplacer_json_out)
        os.system(cmd)
        
        return tree_file
        
    def run(self,
            genomes,
            align_dir,
            out_dir, 
            prefix):
        """Classify genomes based on position in reference tree."""
        
        for marker_set_id in ('bac120', 'ar122'):
            user_msa_file = os.path.join(align_dir, 'gtdbtk.%s.user_msa.fasta' % marker_set_id)
            if not os.path.exists(user_msa_file):
                # file will not exist if there are no User genomes from a given domain
                continue 
            
            classify_tree = self.place_genomes(user_msa_file,
                                                marker_set_id,
                                                out_dir,
                                                prefix)

            # get taxonomic classification of each user genome
            tree = dendropy.Tree.get_from_path(classify_tree, 
                                                schema='newick', 
                                                rooting='force-rooted', 
                                                preserve_underscores=True)
            
            gtdb_taxonomy = Taxonomy().read(self.taxonomy_file)
            
            
            fout = open(os.path.join(out_dir, prefix + '.%s.classification.tsv' % marker_set_id), 'w')
            mashfout = open(os.path.join(out_dir, prefix + '.%s.mash_distance.tsv' % marker_set_id), 'w')
            redfout = open(os.path.join(out_dir, prefix + '.%s.red_value.tsv' % marker_set_id), 'w')
            #parchiinfo = open(os.path.join(out_dir, prefix + '.%s.parentinfo.tsv' % marker_set_id), 'w')

            reddictfile = open(os.path.join(out_dir, prefix + '.%s.red_dictionary.tsv' % marker_set_id), 'w')
            
            marker_dict = {}
            if marker_set_id == 'bac120':
                marker_dict = Config.RED_DIST_BAC_DICT
            elif marker_set_id == 'ar122':
                marker_dict = Config.RED_DIST_ARC_DICT
            reddictfile.write('Phylum\t{0}\n'.format(marker_dict.get('p__')))
            reddictfile.write('Class\t{0}\n'.format(marker_dict.get('c__')))
            reddictfile.write('Order\t{0}\n'.format(marker_dict.get('o__')))
            reddictfile.write('Family\t{0}\n'.format(marker_dict.get('f__')))
            reddictfile.write('Genus\t{0}\n'.format(marker_dict.get('g__')))
            reddictfile.close()
            
            mashfout.write("User genome\tReference genome\tMash distance\n")
            redfout.write("User genome\tRed value\tHigher rank\tHigher value\tLower rank\tLower value\tcase\tclosest_rank\n")
            #parchiinfo.write("User genome\tHigher rank\tHigher value\tLower rank\tLower value\tcase\tclosest_rank\n")
            
            # Genomes can be classified by using Mash or RED values
            # We go through all leaves of the tree. if the leaf is a user genome we take it's parent node and look at all the leaves for this node.
            # If the parent node has only one Reference genome ( GB or RS ) we calculate the mash distance between the user genome and the reference genome
            analysed_nodes = []
            mash_dict = {}
            # some genomes of Case C are handled here, if Mash distance is close enough 
            self.logger.info('Calculating Mash distances.')
            
            
            for nd in tree:
                #We store the prefixes of each leaves to check if one starts with GB_ or RS_
                list_subnode_initials = [subnd.taxon.label.replace("'",'')[0:3] for subnd in nd.leaf_iter()]
                list_subnode = [subnd.taxon.label.replace("'",'') for subnd in nd.leaf_iter()]
                #if only one genome is a reference genome
                if (list_subnode_initials.count('RS_') + list_subnode_initials.count('GB_')) == 1 and len(list_subnode_initials) > 1 and list_subnode[0] not in analysed_nodes:
                    results = self._calculate_mash_distance(list_subnode, genomes)
                    mash_dict = merge_two_dicts(mash_dict,results)
                    analysed_nodes.extend(list_subnode)
               
                    
            for k,v in mash_dict.iteritems():
                suffixed_name = add_ncbi_prefix(v.get("ref_genome"))
                taxa_str = ";".join(gtdb_taxonomy.get(suffixed_name))
                fout.write('%s\t%s\n' % (k, taxa_str))
                mashfout.write("{0}\t{1}\t{2}\n".format(k,v.get("ref_genome"),v.get("mash_dist")))    
            mashfout.close()
            
            self.logger.info('{0} genomes have been classify with Mash.'.format(len(mash_dict)))

            scaled_tree = self._calculate_red_distances(classify_tree, out_dir)
            
            user_genome_ids = set(read_fasta(user_msa_file).keys())
            user_genome_ids = user_genome_ids.difference(set(mash_dict.keys()))
            # for all other cases we measure the RED distance between a leaf and a parent node ( RED = 1-edge_length). This RED value will tell us
            # the rank level that can be associated with a User genome. 
            # As an example if the RED value is close to the order level, the user genome will take the order level of the Reference genome under the same parent node.
            # Is there are multiple orders under the parent node. The user genome is considered as a new order
            countf =0
            countd =0
            counte =0
            counta =0
            countb =0
            countc =0
            countg =0
            for leaf in scaled_tree.leaf_node_iter():
                
                if leaf.taxon.label in user_genome_ids:
                    taxa = []
                    # In some cases , pplacer can associate 2 user genomes on the same parent node so we need to go up the tree to find a node with a reference genome as leaf.
                    edge_length = leaf.edge_length
                    cur_node = leaf.parent_node
                    list_subnode_initials = [subnd.taxon.label.replace("'",'')[0:3] for subnd in cur_node.leaf_iter()]
                    while 'RS_' not in list_subnode_initials and 'GB_' not in list_subnode_initials:
                        edge_length += cur_node.edge_length
                        cur_node = cur_node.parent_node
                        list_subnode_initials = [subnd.taxon.label.replace("'",'')[0:3] for subnd in cur_node.leaf_iter()]
                    
                    red_from_root = cur_node.distance_from_root()
                    
                    red_parent_node  = cur_node.parent_node
                    
                    while red_parent_node is not None and red_parent_node.label is None:
                            red_parent_node =red_parent_node.parent_node
                            
                    higher_rank = red_parent_node.label.split(";")[-1][0:3]
                    higher_rk_val = 0 if higher_rank.startswith('d__') else red_parent_node.distance_from_root()
                    
                    genome_parent_child = [leaf.taxon.label,higher_rank,higher_rk_val,'','','','']
                    
                    
                    lower_rank = []
                    # if the genome is placed between the genus and specie ranks , it will be associated with the genus when _get_closest_red_rank is called
                    if higher_rank != 'g__':
                        subrank = self.order_rank[self.order_rank.index(higher_rank)+1]
                        list_subnode = [subnd.taxon.label.replace("'",'') for subnd in cur_node.leaf_iter() if (subnd.taxon.label.startswith('RS_') or subnd.taxon.label.startswith('GB_'))]
                        list_ranks = ["".join([rank for rank in gtdb_taxonomy.get(name) if rank.startswith(subrank)]) for name in list_subnode]
                        if len(set(list_ranks)) == 1:
                            for subranknd in cur_node.postorder_iter():
                                if subranknd.is_internal() and subranknd.label is not None and subranknd.label.startswith(subrank):
                                    lower_rank = subranknd.label.split(";")
                                    lower_rk_val = subranknd.distance_from_root()
                                    break                             
                    closest_rank = None;
                    
                    if len(lower_rank) == 1 :
                        #if there is only rank on the lower node (i.e genome between p__Nitrospirae and c__Nitrospiria)
                        lrank = lower_rank[0]
                        # if abs(lower_red - genome_red) < abs(higher_red-genome_red) and abs (genome_red - median lower_rank ) < 0.1:
                        if abs(lower_rk_val - (red_from_root)) < abs(higher_rk_val - (red_from_root)) and abs((red_from_root) - marker_dict.get(lrank[:3])) < 0.1:
                            counta += 1
                            genome_parent_child[3]=lrank
                            genome_parent_child[4]=lower_rk_val
                            genome_parent_child[5]='case a'
                            closest_rank = lrank[0:3]
                        # else if abs (genome_red - median higher_rank ) < 0.1:   
                        elif abs((red_from_root) - marker_dict.get(higher_rank[:3])) < 0.1:
                            countb += 1
                            closest_rank = higher_rank[0:3]
                            genome_parent_child[3]=lrank
                            genome_parent_child[4]=lower_rk_val
                            genome_parent_child[5]='case b'               
                        else:
                            closest_rank = self._get_closest_red_rank(red_from_root, marker_dict)
                            genome_parent_child[3]=lrank
                            genome_parent_child[4]=lower_rk_val
                            genome_parent_child[5]='case c'
                            countc += 1 
                    elif len(lower_rank) > 1 :
                        #if there is only rank on the lower node (i.e genome between p__Nitrospirae and c__Nitrospiria;o__Nitrospirales;f__Nitropiraceae)
                        #we loop through the list of rank from lower to higher rank
                        for lrank in reversed(lower_rank):
                            # if lower rank is c__Nitropiria
                            if lrank == lower_rank[0]:
                                # if abs(p__Nitrospirae red - genome_red) < abs(c__Nitrospiria red - genome_red) OR abs(genome_red - median p__Nitrospirae)< abs(genome_red - median c__Nitrospiria)
                                # AND abs(genome_red - median p__Nitrospirae) < 0.1                                                                                   
                                if ((abs(red_from_root-higher_rk_val) < abs(red_from_root - lower_rk_val) )
                                     or abs(red_from_root - marker_dict.get(higher_rank)) < abs(red_from_root-marker_dict.get(lrank[:3]))
                                    and abs(red_from_root - marker_dict.get(higher_rank)) < 0.1):
                                    countd += 1 
                                    closest_rank= higher_rank
                                    genome_parent_child[3]=lrank
                                    genome_parent_child[5]='case d'
                            # if lower rank is o__Nitrospirales 
                            elif lrank != lower_rank[-1]:
                                hsubrank = lower_rank[lower_rank.index(lrank)-1]
                                # if abs(genome_red - median o__Nitrospirales) < abs(genome_red - median c__Nitrospiria) 
                                # and abs(genome_red - median o__Nitrospirales) < 0.1
                                if (abs(red_from_root - marker_dict.get(lrank[:3])) < abs(red_from_root-marker_dict.get(hsubrank[:3]))
                                 and abs(red_from_root - marker_dict.get(lrank[:3])) < 0.1):
                                    counte += 1
                                    closest_rank = lrank[0:3]
                                    genome_parent_child[3]=lrank
                                    genome_parent_child[5]='case e'                                    
                                    
                                    break
                            
                            #else rank is f__Nitropiraceae
                            else:
                                hsubrank = lower_rank[lower_rank.index(lrank)-1]
                                if leaf.taxon.label.startswith('U_65484'):
                                    print 'l:'+lrank
                                    print 'low:'+lower_rank[-1]
                                    print 'h:'+hsubrank
                                
                                #if ( abs( genome red - median f__Nitropiraceae)  < abs(genome red - median o__Nitrospirales) 
                                #    OR abs (genome red - f__Nitropiraceae red ) <  abs(genome red - median o__Nitrospirales) 
                                # AND  abs( genome red - median f__Nitropiraceae) < 0.1
                                if ( (abs(red_from_root-marker_dict.get(lrank[:3])) < abs(red_from_root-marker_dict.get(hsubrank[:3]))
                                      or abs(red_from_root - lower_rk_val) < abs(red_from_root-marker_dict.get(hsubrank[:3])) )
                                     and abs(red_from_root - marker_dict.get(lrank[:3])) < 0.1):
                                    if leaf.taxon.label.startswith('U_65484'):
                                        print abs(red_from_root-lower_rk_val)
                                        print abs(red_from_root-marker_dict.get(hsubrank[:3]))
                                        print abs(red_from_root - marker_dict.get(lrank[:3]))       
                                    countf += 1 
                                    closest_rank = lrank[0:3]
                                    genome_parent_child[3]=lrank
                                    genome_parent_child[4]=lower_rk_val
                                    genome_parent_child[5]='case f'   
                                    break
                           
                    if closest_rank is None:
                        countg += 1
                        closest_rank = self._get_closest_red_rank((1-edge_length), marker_dict)
                        genome_parent_child[3]=closest_rank
                        genome_parent_child[5]='case g'
                        
                    genome_parent_child[6]=closest_rank                   
                    
                                        
                    list_subnode = [subnd.taxon.label.replace("'",'') for subnd in cur_node.leaf_iter()]
                    
                    if (list_subnode_initials.count('RS_') + list_subnode_initials.count('GB_')) == 1 : 
                        # Case c,d,e in the manuscripts
                        red_taxonomy = self._get_redtax_single_ref(list_subnode,closest_rank,gtdb_taxonomy)
                    else :
                        #Case a,b,d
                        red_taxonomy = self._get_redtax_multi_ref(list_subnode,closest_rank,gtdb_taxonomy)
                    fout.write('{0}\t{1}\n'.format(leaf.taxon.label, red_taxonomy,))
                    del genome_parent_child[0]
                    redfout.write('{0}\t{1}\t{2}\n'.format(leaf.taxon.label,1-edge_length,'\t'.join(str(x) for x in genome_parent_child)))

            print "count a: {0}".format(counta)
            print "count b: {0}".format(countb)
            print "count c: {0}".format(countc)                    
            print "count d: {0}".format(countd)
            print "count e: {0}".format(counte)
            print "count f: {0}".format(countf)
            print "count g: {0}".format(countg)

            redfout.close()
            fout.close()

            pplaceout = open(os.path.join(out_dir, prefix + '.%s.classification_pplacer.tsv' % marker_set_id), 'w')        
            
            # We get the pplacer taxonomy for comparison
            user_genome_ids = set(read_fasta(user_msa_file).keys())
            for leaf in tree.leaf_node_iter():
                if leaf.taxon.label in user_genome_ids:
                    taxa = []
                    cur_node = leaf
                    while cur_node.parent_node:
                        _support, taxon, _aux_info = parse_label(cur_node.label)      
                        if taxon:
                            for t in taxon.split(';')[::-1]:
                                taxa.append(t.strip())                           
                        cur_node = cur_node.parent_node
                    taxa_str = ';'.join(taxa[::-1])
                    pplaceout.write('%s\t%s\n' % (leaf.taxon.label, taxa_str))
            pplaceout.close()
            
    def _parse_subtree(self,cur_node,dict_subrank,lower_rank):
        
        for childn in cur_node.child_nodes():
            if childn.is_leaf():
                continue
            elif childn.label is not None and childn.label.startswith(lower_rank):
                dict_subrank[childn.label]=abs(1-childn.edge_length)
            else:
                dict_subrank = self._parse_subtree(childn,dict_subrank,lower_rank)
        return dict_subrank
            
        
    def _get_closest_red_rank(self,red_value,marker_dict):
        """Compare the absolute difference between the user genome edge length and the list of 
        RED value for each rank of the reference tree.
        The smallest difference is chosen and the rank of preference is returned.
        
        Parameters
        ----------
        red_value : Red value of the user genome.
    
        Returns
        -------
        string
            Chosen rank prefix (p__,c__,o__...).
        
        """
        key, value = min(marker_dict.items(), key=lambda (_, v): abs(v - red_value))
        #print value-red_value
        return key
    
    def _get_redtax_single_ref(self,list_subnode,closest_rank,gtdb_taxonomy):
        """
        Get the taxonomy of the selected reference genome.
        The taxonomy will stop at a specific rank
        
        Parameters
        ----------
        list_subnode : list of leaf nodes including one reference genome.
        closest_rank : last rank of the reference taxonomy
        gtdb_taxonomy : dictionary storing all the reference taxonomies
        
    
        Returns
        -------
        string
            Taxonomy string.
        
        """
        taxonomy = ''
        subtax = []
        for item in list_subnode:
            if item.startswith('RS_') or item.startswith('GB_'):
                taxonomy_from_file = gtdb_taxonomy.get(item)
                for rank in taxonomy_from_file:
                    if rank.startswith(closest_rank):
                        subtax.append(rank)
                        break
                    else:
                        subtax.append(rank)
        return ';'.join(subtax)
    
    def _get_redtax_multi_ref(self,list_subnode,closest_rank,gtdb_taxonomy):
        """
        Provide a taxonomy string to a user genome based on the reference genomes of the same clade.
        If the clade contains multiple reference genomes we are comparing their taxonomies.
        -If all reference genomes have the same taxonomy up to the 'closest rank' ,
        the taxonomy string including the closest rank is returned.
        -If **NOT** all reference genomes have the same taxonomy up to the 'closest rank',
        the taxonomy string **NOT** including the closest rank is returned.
       
        Parameters
        ----------
        list_subnode : list of leaf nodes including multiple reference genome.
        closest_rank : last rank of the reference taxonomy
        gtdb_taxonomy : dictionary storing all the reference taxonomies
        
    
        Returns
        -------
        string
            Taxonomy string.
        
        """
        taxonomy = ''

        subtax,multirefrank = self._parse_subnodes(list_subnode,closest_rank,gtdb_taxonomy)
        # if all orders in the list are the same, the user genomes gets the same order  
        if len(set(multirefrank)) == 1 :
            #case d
            subtax.append(multirefrank[0])
        else:
            #otherwise it's stored as undefined
            #case a,b
            subtax.append(closest_rank+"undefined")
        return ';'.join(subtax)
    
    def _parse_subnodes(self,list_subnode,closest_rank,gtdb_taxonomy):
        subtax = []
        multirefrank = []
        initial_loop = True
        for item in list_subnode:
            # We get the taxonomy of all reference genomes
            if item.startswith('RS_') or item.startswith('GB_'):
                taxonomy_from_file = gtdb_taxonomy.get(item)
                # we store the selected rank (i.e. order) for each reference genome 
                for rank in taxonomy_from_file:
                    if rank.startswith(closest_rank):
                        multirefrank.append(rank)
                        initial_loop = False
                        break
                    elif initial_loop:
                        # The first iteration is used to stored upper level ( i.e. domain,phylum,class )
                        subtax.append(rank)
        return subtax,multirefrank
        
    def _calculate_red_distances(self,input_tree,out_dir):
        """
        Provide a taxonomy string to a user genome based on the reference genomes of the same clade.
        If the clade contains multiple reference genomes we are comparing their taxonomies.
        -If all reference genomes have the same taxonomy up to the 'closest rank' ,
        the taxonomy string including the closest rank is returned.
        -If **NOT** all reference genomes have the same taxonomy up to the 'closest rank',
        the taxonomy string **NOT** including the closest rank is returned.
       
        Parameters
        ----------
        list_subnode : list of leaf nodes including multiple reference genome.
        closest_rank : last rank of the reference taxonomy
        gtdb_taxonomy : dictionary storing all the reference taxonomies
        
    
        Returns
        -------
        string
            Taxonomy string.
        """
        
        # read tree
        self.logger.info('Reading tree.')
        tree = dendropy.Tree.get_from_path(input_tree, 
                                            schema='newick', 
                                            rooting='force-rooted', 
                                            preserve_underscores=True)

        self.logger.info('Reading taxonomy from file.')
        taxonomy = Taxonomy().read(Config.TAXONOMY_FILE)

        # determine taxa to be used for inferring distribution
        trusted_taxa = None
        taxa_for_dist_inference = self._filter_taxa_for_dist_inference(tree, 
                                                                 taxonomy, 
                                                                 trusted_taxa, 
                                                                 Config.RED_MIN_CHILDREN, 
                                                                 Config.RED_MIN_SUPPORT)
            
        phylum_rel_dists, rel_node_dists = self.median_rd_over_phyla(tree, 
                                                                        taxa_for_dist_inference,
                                                                        taxonomy)
                                                                        
        # set edge lengths to median value over all rootings
        tree.seed_node.rel_dist = 0.0
        for n in tree.preorder_node_iter(lambda n: n != tree.seed_node):
            n.rel_dist = np_median(rel_node_dists[n.id])
            rd_to_parent = n.rel_dist - n.parent_node.rel_dist
            if rd_to_parent < 0:
                # This can occur since we are setting all nodes
                # to their median RED value.
                #self.logger.warning('Not all branches are positive after scaling.')
                pass
            n.edge_length = rd_to_parent
        
        if False:
            # These plots can be useful for debugging and internal use,
            # but are likely to be confusing to users.
            rd = RelativeDistance()

            input_tree_name = os.path.splitext(os.path.basename(input_tree))[0]
            plot_file = os.path.join(out_dir, '%s.png' % input_tree_name)
            rd._distribution_summary_plot(phylum_rel_dists, taxa_for_dist_inference, plot_file)

            gtdb_parent_ranks = Taxonomy().parents(taxonomy)
            median_outlier_table = os.path.join(out_dir, '%s.tsv' % input_tree_name)
            median_rank_file = os.path.join(out_dir, '%s.dict' % input_tree_name)
            rd._median_summary_outlier_file(phylum_rel_dists, 
                                                 taxa_for_dist_inference, 
                                                 gtdb_parent_ranks, 
                                                 median_outlier_table, 
                                                 median_rank_file, 
                                                 False)
                                            
        
            output_tree = os.path.join(out_dir, '%s.scaled.tree' % input_tree_name)
            tree.write_to_path(output_tree, 
                            schema='newick', 
                            suppress_rooting=True, 
                            unquoted_underscores=True)
        
        return tree

    def _calculate_mash_distance(self,list_leaf,genomes):

        """ Calculate the Mash distance between all user genomes and the reference to classfy them at the species level
        
        Parameters
        ----------
        list_leaf : List of leaves uncluding one or many user genomes and one reference genome.
        genomes : Dictionary of user genomes d[genome_id] -> FASTA file
    
        Returns
        -------
        dictionary
            dict_results[user_g]={"ref_genome":ref_genome,"mash_dist":mash_dist}
        
        """
        try:
            self.tmp_output_dir = tempfile.mkdtemp()
            usr_genome_dir = os.path.join(self.tmp_output_dir, 'input_genomes')
            make_sure_path_exists(usr_genome_dir)
            for leaf in list_leaf:
                if not leaf.startswith('GB_') and not leaf.startswith('RS_'):
                    shutil.copy(genomes.get(leaf), usr_genome_dir)
                    
            cmd = 'mash sketch -s 5000 -k 16 -o {0}/user_genomes {1}/* -p {2} > /dev/null 2>&1'.format(self.tmp_output_dir, usr_genome_dir, self.cpus)
            os.system(cmd)
            reference_db = os.path.join(Config.MASH_DIR,Config.MASH_DB)
            cmd = 'mash dist {0} {1}/user_genomes.msh -p {2} -d {3}> {1}/distances.tab'.format(reference_db,self.tmp_output_dir,self.cpus,Config.MASH_SPECIES_THRESHOLD) 
            os.system(cmd)
            if not os.path.isfile(os.path.join(self.tmp_output_dir,'user_genomes.msh')) or not os.path.isfile(os.path.join(self.tmp_output_dir,'distances.tab')):
                raise
            dict_parser_distance = self._parse_mash_results(os.path.join(self.tmp_output_dir,'distances.tab'),list_leaf)
            return dict_parser_distance
              
        except:
            if os.path.exists(self.tmp_output_dir):
                shutil.rmtree(self.tmp_output_dir)
            raise
        
    def _parse_mash_results(self,distance_file,list_leaf):
        """ Parse the mash output file
        
        
        Parameters
        ----------
        distance_file : Mash output file.
    
        Returns
        -------
        dictionary
            dict_results[user_g]={"ref_genome":ref_genome,"mash_dist":mash_dist}
        """
        dict_results = {}
        with open(distance_file) as distfile:
            for line in distfile:
                info = line.strip().split("\t")
                ref_genome = "_".join(info[0].split("_", 2)[:2])
                suffixed_name = add_ncbi_prefix(ref_genome)
                if suffixed_name not in list_leaf:
                    continue
                user_g = remove_extension(os.path.basename(info[1]))
                mash_dist = float(info[2])
                if user_g in dict_results:
                    if mash_dist < dict_results.get(user_g).get("mash_dist"):
                        dict_results[user_g]={"ref_genome":ref_genome,"mash_dist":mash_dist}
                else:
                    dict_results[user_g]={"ref_genome":ref_genome,"mash_dist":mash_dist}
        return dict_results
    
    def _filter_taxa_for_dist_inference(self,tree, taxonomy, trusted_taxa, min_children, min_support):
        """Determine taxa to use for inferring distribution of relative divergences.
    
        Parameters
        ----------
        tree : Dendropy Tree
            Phylogenetic tree.
        taxonomy : d[taxon ID] -> [d__x; p__y; ...]
            Taxonomy for each taxon.
        trusted_taxa : iterable
            Trusted taxa to consider when inferring distribution.
        min_children : int
            Only consider taxa with at least the specified number of children taxa when inferring distribution.
        min_support : float
            Only consider taxa with at least this level of support when inferring distribution.
        """
    
        # determine children taxa for each named group
        taxon_children = Taxonomy().taxon_children(taxonomy)
    
        # get all named groups
        taxa_for_dist_inference = set()
        for taxon_id, taxa in taxonomy.iteritems():
            for taxon in taxa:
                taxa_for_dist_inference.add(taxon)
    
        # sanity check species names as these are a common problem
        species = set()
        for taxon_id, taxa in taxonomy.iteritems():
            if len(taxa) > Taxonomy.rank_index['s__']:
                species_name = taxa[Taxonomy.rank_index['s__']]
                valid, error_msg = True, None
                if species_name != 's__':
                    valid, error_msg = Taxonomy().validate_species_name(species_name, require_full=True, require_prefix=True)
                if not valid:
                    print '[Warning] Species name %s for %s is invalid: %s' % (species_name, taxon_id, error_msg)
                    continue
                    
                species.add(species_name)
    
        # restrict taxa to those with a sufficient number of named children
        # Note: a taxonomic group with no children will not end up in the
        # taxon_children data structure so care must be taken when applying
        # this filtering criteria.
        if min_children > 0:
            valid_taxa = set()
            for taxon, children_taxa in taxon_children.iteritems():
                if len(children_taxa) >= min_children:
                    valid_taxa.add(taxon)
    
            taxa_for_dist_inference.intersection_update(valid_taxa)
    
            # explicitly add in the species since they have no
            # children and thus be absent from the taxon_child dictionary
            taxa_for_dist_inference.update(species)
    
        # restrict taxa used for inferring distribution to those with sufficient support
        if min_support > 0:
            for node in tree.preorder_node_iter():
                if not node.label or node.is_leaf():
                    continue
    
                # check for support value
                support, taxon_name, _auxiliary_info = parse_label(node.label)
    
                if not taxon_name:
                    continue
    
                if support and float(support) < min_support:
                    taxa_for_dist_inference.difference_update([taxon_name])
                elif not support and min_support > 0:
                    # no support value, so inform user if they were trying to filter on this property
                    print '[Error] Tree does not contain support values. As such, --min_support should be set to 0.'
                    continue
    
        # restrict taxa used for inferring distribution to the trusted set
        if trusted_taxa:
            taxa_for_dist_inference = trusted_taxa.intersection(taxa_for_dist_inference)
    
        return taxa_for_dist_inference
    
    def median_rd_over_phyla(self, 
                                tree, 
                                taxa_for_dist_inference,
                                taxonomy):
        """Calculate the median relative divergence over all phyla rootings.
        
        Parameters
        ----------
        tree : Tree
          Dendropy tree.
        taxa_for_dist_inference : set
          Taxa to use for inference relative divergence distributions.
        taxonomy : d[taxon_id] -> [d__, p__, ..., s__]
          Taxonomy of extant taxa.
        """
    
        # get list of phyla level lineages
        all_phyla = self._get_phyla_lineages(tree)
        self.logger.info('Identified %d phyla.' % len(all_phyla))
        
        phyla = [p for p in all_phyla if p in taxa_for_dist_inference]
        self.logger.info('Using %d phyla as rootings for inferring RED distributions.' % len(phyla))
        if len(phyla) < 2:
            self.logger.error('Rescaling requires at least 2 valid phyla.')
            sys.exit(-1)
            
        # give each node a unique id
        for i, n in enumerate(tree.preorder_node_iter()):
            n.id = i
    
        # calculate relative divergence for tree rooted on each phylum
        phylum_rel_dists = {}
        rel_node_dists = defaultdict(list)
        rd = RelativeDistance()
        for p in phyla:
            phylum = p.replace('p__', '').replace(' ', '_').lower()
            status_msg = '==> Calculating information with rooting on %s.              ' % phylum.capitalize()
            sys.stdout.write('%s\r' % status_msg)
            sys.stdout.flush()

            cur_tree = self.root_with_outgroup(tree, taxonomy, p)
            
            # calculate relative distance to taxa
            rel_dists = rd.rel_dist_to_named_clades(cur_tree)
            rel_dists.pop(0, None) # remove results for Domain

            # remove named groups in outgroup
            children = Taxonomy().children(p, taxonomy)
            for r in rel_dists.keys():
                rel_dists[r].pop(p, None)

            for t in children:
                for r in rel_dists.keys():
                    rel_dists[r].pop(t, None)

            phylum_rel_dists[phylum] = rel_dists
            
            # calculate relative distance to all nodes
            rd.decorate_rel_dist(cur_tree)
            
            # determine which lineages represents the 'ingroup'
            ingroup_subtree = None
            for c in cur_tree.seed_node.child_node_iter():
                _support, taxon_name, _auxiliary_info = parse_label(c.label)
                if not taxon_name or p not in taxon_name:
                    ingroup_subtree = c
                    break
            
            # do a preorder traversal of 'ingroup' and record relative divergence to nodes
            for n in ingroup_subtree.preorder_iter():
                rel_node_dists[n.id].append(n.rel_dist)
                
        #status_msg = 'Inference of RED distribution finished'
        #sys.stdout.write('%s\r' % status_msg)
        sys.stdout.write('==> Inference for RED distributions finished.                         ')
        sys.stdout.flush()
        #self.logger.info('Inference for RED distributions finished.')
        sys.stdout.write('\n')
        
        return phylum_rel_dists, rel_node_dists
    
    def _get_phyla_lineages(self,tree):
        """Get list of phyla level lineages.
    
        Parameters
        ----------
        tree : Dendropy Tree
            Phylogenetic tree.
    
        Returns
        -------
        list
            List of phyla level lineages.
        """
        phyla = []
        for node in tree.preorder_node_iter():
            if not node.label or node.is_leaf():
                continue
    
            _support, taxon_name, _auxiliary_info = parse_label(node.label)
            if taxon_name:
                taxa = [x.strip() for x in taxon_name.split(';')]
                if taxa[-1].startswith('p__'):
                    phyla.append(taxa[-1])
                    
        return phyla
    
    def root_with_outgroup(self, input_tree, taxonomy, outgroup_taxa):
        """Reroot the tree using the given outgroup.

        Parameters
        ----------
        input_tree : Dendropy Tree
          Tree to rerooted.
        taxonomy : dict
            Taxonomy for taxa.
        outgroup : iterable
          Labels of taxa in outgroup.
          
        Returns
        -------
        Dendropy Tree
            Deep-copy of original tree rerooted on outgroup.
        """
        
        new_tree = input_tree.clone()
        
        outgroup = set()
        for genome_id, taxa in taxonomy.iteritems():
            if outgroup_taxa in taxa:
                outgroup.add(genome_id)
                
        outgroup_in_tree = set()
        ingroup_in_tree = set()
        for n in new_tree.leaf_node_iter():
            if n.taxon.label in outgroup:
                outgroup_in_tree.add(n.taxon)
            else:
                ingroup_in_tree.add(n)

        if len(outgroup_in_tree) == 0:
            self.logger.warning('No outgroup taxa identified in the tree.')
            self.logger.warning('Tree was not rerooted.')
            sys.exit(0)
            
        # There is a complication here. We wish to find the MRCA of the outgroup
        # taxa. Finding the MRCA requires a rooted tree and we have no gaurantee
        # that the tree isn't currently rooted within the outgroup clade. There is
        # also no way to identify a node that is gauranteed to be outside the outgroup
        # clade. As such, the tree is randomly rooted on a leaf node not in the outgroup.
        # This random rerooting is performed until the MRCA does not spans all taxa in 
        # the tree.

        leaves_in_tree = sum([1 for _ in new_tree.leaf_node_iter()])
        while True:
            rnd_ingroup_leaf = random.sample(ingroup_in_tree, 1)[0]
            new_tree.reroot_at_edge(rnd_ingroup_leaf.edge,
                                    length1=0.5 * rnd_ingroup_leaf.edge_length,
                                    length2=0.5 * rnd_ingroup_leaf.edge_length)

            mrca = new_tree.mrca(taxa=outgroup_in_tree)
            leaves_in_mrca = sum([1 for _ in mrca.leaf_iter()])
            if leaves_in_mrca != leaves_in_tree:
                break

        if leaves_in_mrca == leaves_in_tree:
            self.logger.error('The MRCA spans all taxa in the tree.')
            self.logger.error('This indicating the selected outgroup is likely polyphyletic in the current tree.')
            self.logger.error('This should never occur. Please report this as a bug.')
            sys.exit(-1)

        if mrca.edge_length is None:
            #self.logger.info('Tree appears to already be rooted on this outgroup.')
            pass
        else:
            new_tree.reroot_at_edge(mrca.edge,
                                length1=0.5 * mrca.edge_length,
                                length2=0.5 * mrca.edge_length)
        
        return new_tree
              